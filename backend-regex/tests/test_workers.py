"""Tests des workers Celery."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from workers.celery_app import celery_app, health_check_task
from workers.tasks import (
    analyze_with_llm,
    ingest_document,
    process_search,
    run_detection,
    run_eval_search,
    run_find_experiment,
)


def test_celery_app_config():
    """Vérifie la configuration de l'app Celery."""
    assert celery_app.main == "docs_regex_workers"
    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.accept_content == ["json"]
    assert celery_app.conf.result_serializer == "json"
    assert celery_app.conf.enable_utc is True


def test_celery_task_routing():
    """Vérifie que les routes des tâches sont configurées."""
    routes = celery_app.conf.task_routes
    assert "workers.tasks.ingest_document" in routes
    assert "workers.tasks.process_search" in routes
    assert "workers.tasks.run_detection" in routes
    assert "workers.tasks.run_eval_search" in routes
    assert "workers.tasks.run_find_experiment" in routes


def test_health_check_task_signature():
    """Vérifie que la tâche health_check est bien définie."""
    assert health_check_task.name == "workers.health_check"
    assert callable(health_check_task)


def test_ingest_document_task_exists():
    """Vérifie que la tâche ingest_document existe."""
    assert ingest_document.name == "workers.tasks.ingest_document"
    # Note: on ne peut pas exécuter la tâche sans worker Celery actif


def test_process_search_task_exists():
    """Vérifie que la tâche process_search existe."""
    assert process_search.name == "workers.tasks.process_search"


def test_process_search_task_runs_pipeline():
    """Vérifie que process_search délègue bien au SearchPipeline."""

    class _FakePipeline:
        async def run(self, query: str, index_name: str, top_k: int, strategy: str):
            assert query == "budget"
            assert index_name == "docs"
            assert top_k == 10
            assert strategy == "hybrid"
            return {
                "status": "completed",
                "query": query,
                "index_name": index_name,
                "strategy": strategy,
                "count": 1,
                "results": [{"id": "ev-1", "score": 0.9}],
            }

    with patch("workers.tasks.SearchPipeline", return_value=_FakePipeline()):
        result = process_search.run(query="budget", index_name="docs")

    assert result["status"] == "completed"
    assert result["count"] == 1


def test_run_detection_task_exists():
    """Vérifie que la tâche run_detection existe."""
    assert run_detection.name == "workers.tasks.run_detection"


def test_run_detection_task_runs_pipeline():
    """run_detection should load extracted content and call DetectionPipeline."""

    class _FakeDetectionPipeline:
        def run(self, document_id: str, claims: list[str], markdown: str, layout: list):
            assert document_id == "doc_1"
            assert claims == ["claim-a"]
            assert "Budget" in markdown
            return {
                "status": "completed",
                "document_id": document_id,
                "claims_count": 1,
                "conflict_count": 1,
                "severity": "high",
                "recommendation": "Escalate to reviewer before validation.",
                "llm_required": True,
                "results": [],
            }

    with patch("workers.tasks.get_minio_storage") as mock_storage_factory, patch("workers.tasks.DetectionPipeline", return_value=_FakeDetectionPipeline()):
        mock_storage = MagicMock()
        mock_storage.get_extracted_content.return_value = {"markdown": "Budget 900 EUR", "layout": []}
        mock_storage_factory.return_value = mock_storage

        result = run_detection.run(document_id="doc_1", claim_ids=["claim-a"])

    assert result["status"] == "completed"
    assert result["severity"] == "high"


def test_run_detection_missing_content():
    """run_detection should return error when extracted content is unavailable."""
    with patch("workers.tasks.get_minio_storage") as mock_storage_factory:
        mock_storage = MagicMock()
        mock_storage.get_extracted_content.return_value = None
        mock_storage_factory.return_value = mock_storage

        result = run_detection.run(document_id="missing", claim_ids=["claim-a"])

    assert result["status"] == "error"
    assert "not found" in result["error"].lower()


def test_analyze_with_llm_task_exists():
    """Vérifie que la tâche analyze_with_llm existe."""
    assert analyze_with_llm.name == "workers.tasks.analyze_with_llm"


def test_analyze_with_llm_task_success():
    """analyze_with_llm should call LiteLLM client."""

    class _FakeLiteLLMClient:
        def analyze_sync(self, prompt: str, model: str | None = None, temperature: float = 0.0, max_tokens: int | None = None):
            return {
                "status": "completed",
                "model": model or "x",
                "content": "analysis output",
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }

    with patch("workers.tasks.LiteLLMClient", return_value=_FakeLiteLLMClient()):
        result = analyze_with_llm.run(prompt="hello", model="openrouter/test-model")

    assert result["status"] == "completed"
    assert result["model"] == "openrouter/test-model"
    assert result["content"] == "analysis output"


def test_run_eval_search_task_exists():
    assert run_eval_search.name == "workers.tasks.run_eval_search"


def test_run_eval_search_task_runs():
    class _FakeRunner:
        async def evaluate_search(self, samples, corpus, strategy: str, top_k: int):
            assert strategy == "baseline"
            assert top_k == 3
            assert len(samples) == 1
            assert len(corpus) == 1
            return {"strategy": strategy, "samples": 1, "mean_recall_at_k": 1.0}

    with patch("workers.tasks.EvaluationRunner", return_value=_FakeRunner()):
        result = run_eval_search.run(
            samples=[
                {
                    "sample_id": "s1",
                    "query": "deadline",
                    "relevant_ids": ["doc-1"],
                    "relevance_by_id": {"doc-1": 1.0},
                    "index_name": "default",
                }
            ],
            corpus=[{"id": "doc-1", "text": "deadline"}],
            strategy="baseline",
            top_k=3,
        )
    assert result["samples"] == 1


def test_run_find_experiment_task_exists():
    assert run_find_experiment.name == "workers.tasks.run_find_experiment"


def test_run_find_experiment_task_runs():
    class _FakeRunner:
        async def run_find_experiment(
            self,
            dataset_name: str,
            split: str,
            max_samples: int,
            index_name: str,
            top_k: int,
            strategies: list[str] | None,
            streaming: bool,
            cache_dir: str | None,
            max_query_chars: int,
        ):
            assert dataset_name == "kensho/FIND"
            assert split == "validation"
            assert max_samples == 10
            assert index_name == "default"
            assert top_k == 5
            assert strategies == ["baseline", "semantic"]
            assert streaming is True
            assert max_query_chars == 8192
            return {"dataset_name": "kensho/FIND", "samples_count": 1}

    with patch("workers.tasks.EvaluationRunner", return_value=_FakeRunner()):
        result = run_find_experiment.run(
            dataset_name="kensho/FIND",
            split="validation",
            max_samples=10,
            index_name="default",
            top_k=5,
            strategies=["baseline", "semantic"],
            streaming=True,
        )
    assert result["dataset_name"] == "kensho/FIND"


def test_ingest_document_s3_success():
    """Vérifie le traitement complet d'un fichier source MinIO S3."""
    captured = {}

    class FakeUsage:
        def model_dump(self):
            return {"total_tokens": 10}

    class FakeResponse:
        id = "ocr-task-123"
        model = "glm-ocr"
        usage = FakeUsage()
        md_results = "# Parsed content"
        layout_details = [[{"index": 1}], [{"index": 2}, {"index": 3}]]

        def model_dump(self):
            return {"id": self.id, "model": self.model}

    async def fake_parse_document(file, is_url, return_crop_images, need_layout_visualization):
        captured["temp_file"] = file
        captured["is_url"] = is_url
        return FakeResponse()

    class _FakeSearchPipeline:
        async def index_evidence_units(self, evidence_units, index_name: str):
            assert index_name == "default"
            assert len(evidence_units) == 1
            return {"status": "ok"}

    with patch("workers.tasks.get_ocr_client") as mock_get_ocr, patch("workers.tasks.get_minio_storage") as mock_get_storage, patch("workers.tasks.SearchPipeline", return_value=_FakeSearchPipeline()):
        mock_ocr = MagicMock()
        mock_ocr.parse_document = fake_parse_document
        mock_get_ocr.return_value = mock_ocr

        mock_storage = MagicMock()
        mock_storage.get_file_content.return_value = b"%PDF-1.4 test content"
        mock_storage.save_extracted_content = MagicMock()
        mock_get_storage.return_value = mock_storage

        result = ingest_document.run(
            document_id="doc_123",
            file_path="s3://documents/doc_123/uploaded.pdf",
            filename="uploaded.pdf",
            is_url=False,
        )

    assert result["status"] == "completed"
    assert result["document_id"] == "doc_123"
    assert result["num_pages"] == 2
    assert result["num_elements"] == 3
    assert result["model_used"] == "glm-ocr"
    assert result["index_status"] == "completed"
    assert result["indexed_count"] == 1
    assert captured["is_url"] is False
    assert captured["temp_file"].endswith(".pdf")
    assert not os.path.exists(captured["temp_file"])
    mock_storage.get_file_content.assert_called_once_with("doc_123", "uploaded.pdf")
    mock_storage.save_extracted_content.assert_called_once()


def test_ingest_document_s3_file_missing():
    """Vérifie qu'on remonte une erreur explicite si le fichier S3 est introuvable."""
    with patch("workers.tasks.get_ocr_client") as mock_get_ocr, patch("workers.tasks.get_minio_storage") as mock_get_storage:
        mock_get_ocr.return_value = MagicMock()
        mock_storage = MagicMock()
        mock_storage.get_file_content.return_value = None
        mock_get_storage.return_value = mock_storage

        result = ingest_document.run(
            document_id="doc_404",
            file_path="s3://documents/doc_404/missing.pdf",
            filename="missing.pdf",
            is_url=False,
        )

    assert result["status"] == "error"
    assert "Unable to load file from MinIO" in result["error"]


def test_ingest_document_indexing_failure_is_non_blocking():
    """OCR ingestion should still complete even if indexing fails."""

    class FakeResponse:
        id = "ocr-task-123"
        model = "glm-ocr"
        usage = None
        md_results = "# Parsed content"
        layout_details = [[{"index": 1, "label": "text", "content": "Only one"}]]

        def model_dump(self):
            return {"id": self.id, "model": self.model}

    async def fake_parse_document(file, is_url, return_crop_images, need_layout_visualization):
        return FakeResponse()

    class _BrokenSearchPipeline:
        async def index_evidence_units(self, evidence_units, index_name: str):
            raise RuntimeError("nextplaid unavailable")

    with patch("workers.tasks.get_ocr_client") as mock_get_ocr, patch("workers.tasks.get_minio_storage") as mock_get_storage, patch("workers.tasks.SearchPipeline", return_value=_BrokenSearchPipeline()):
        mock_ocr = MagicMock()
        mock_ocr.parse_document = fake_parse_document
        mock_get_ocr.return_value = mock_ocr

        mock_storage = MagicMock()
        mock_storage.get_file_content.return_value = b"%PDF-1.4 test content"
        mock_storage.save_extracted_content = MagicMock()
        mock_get_storage.return_value = mock_storage

        result = ingest_document.run(
            document_id="doc_123",
            file_path="s3://documents/doc_123/uploaded.pdf",
            filename="uploaded.pdf",
            is_url=False,
        )

    assert result["status"] == "completed"
    assert result["index_status"] == "failed"


def test_ingest_document_ocr_upload_timeout_returns_explicit_error():
    async def fake_parse_document(file, is_url, return_crop_images, need_layout_visualization):
        raise httpx.WriteTimeout("timed out")

    with patch("workers.tasks.get_ocr_client") as mock_get_ocr, patch("workers.tasks.get_minio_storage") as mock_get_storage:
        mock_ocr = MagicMock()
        mock_ocr.parse_document = fake_parse_document
        mock_get_ocr.return_value = mock_ocr

        mock_storage = MagicMock()
        mock_storage.get_file_content.return_value = b"%PDF-1.4 test content"
        mock_get_storage.return_value = mock_storage

        result = ingest_document.run(
            document_id="doc_timeout",
            file_path="s3://documents/doc_timeout/uploaded.pdf",
            filename="uploaded.pdf",
            is_url=False,
        )

    assert result["status"] == "error"
    assert "OCR upload timed out" in result["error"]
    mock_storage.set_processing_status.assert_called()
