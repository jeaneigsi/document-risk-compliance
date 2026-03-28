"""Tests for document ingest API routes."""

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.eval.datasets import FindEvalPackError


@pytest.fixture
def test_client():
    """Create test client for FastAPI app."""
    # Import app here to ensure routes are included
    from app.api.main import app
    return TestClient(app)


@pytest.fixture
def mock_storage():
    """Mock MinIO storage."""
    with patch("app.api.routes.get_minio_storage") as mock:
        storage = MagicMock()
        storage.save_uploaded_file = MagicMock(return_value="doc_123/file.pdf")
        storage._get_metadata = MagicMock(return_value=None)
        storage.get_extracted_content = MagicMock(return_value=None)
        storage.delete_document = MagicMock(return_value=True)
        storage.list_documents = MagicMock(return_value=[])
        storage.health_check = MagicMock(return_value=True)
        storage._sanitize_filename = lambda x: x
        mock.return_value = storage
        yield storage


@pytest.fixture
def mock_ocr():
    """Mock OCR client."""
    with patch("app.api.routes.get_ocr_client") as mock:
        ocr = AsyncMock()
        ocr.health_check = AsyncMock(return_value=True)
        mock.return_value = ocr
        yield ocr


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    def test_health_all_healthy(self, test_client, mock_storage, mock_ocr):
        """Test health check when all services are healthy."""
        mock_storage.health_check.return_value = True

        response = test_client.get("/api/v1/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["version"] == "0.1.0"
        assert data["components"]["ocr"] == "ok"
        assert data["components"]["minio"] == "ok"

    def test_health_degraded(self, test_client, mock_storage, mock_ocr):
        """Test health check when a service is down."""
        mock_storage.health_check.return_value = False

        response = test_client.get("/api/v1/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["components"]["minio"] == "error"


class TestDocumentUpload:
    """Tests for /documents/upload endpoint."""

    def test_upload_pdf_success(self, test_client, mock_storage, mock_ocr):
        """Test successful PDF upload."""
        content = b"%PDF-1.4 fake pdf content"
        files = {"file": ("test.pdf", io.BytesIO(content), "application/pdf")}

        response = test_client.post("/api/v1/documents/upload", files=files)

        assert response.status_code == 200
        data = response.json()
        assert "document_id" in data
        assert data["filename"] == "test.pdf"
        assert data["status"] == "pending"
        assert data["size_bytes"] == len(content)
        mock_storage.save_uploaded_file.assert_called_once()

    def test_upload_jpeg_success(self, test_client, mock_storage, mock_ocr):
        """Test successful JPEG upload."""
        content = b"\xff\xd8\xff\xe0 fake jpeg"
        files = {"file": ("test.jpg", io.BytesIO(content), "image/jpeg")}

        response = test_client.post("/api/v1/documents/upload", files=files)

        assert response.status_code == 200
        data = response.json()
        assert data["filename"] == "test.jpg"

    def test_upload_file_too_large_pdf(self, test_client, mock_storage, mock_ocr):
        """Test upload fails for oversized PDF."""
        # 51MB PDF
        content = b"%PDF-1.4 " + b"x" * (51 * 1024 * 1024)
        files = {"file": ("large.pdf", io.BytesIO(content), "application/pdf")}

        response = test_client.post("/api/v1/documents/upload", files=files)

        assert response.status_code == 413
        assert "too large" in response.json()["detail"]

    def test_upload_unsupported_format(self, test_client, mock_storage, mock_ocr):
        """Test upload fails for unsupported file type."""
        content = b"some content"
        files = {"file": ("test.txt", io.BytesIO(content), "text/plain")}

        response = test_client.post("/api/v1/documents/upload", files=files)

        assert response.status_code == 400
        assert "Unsupported file type" in response.json()["detail"]


class TestDocumentStatus:
    """Tests for /documents/{id}/status endpoint."""

    def test_status_completed(self, test_client, mock_storage):
        """Test status for completed document."""
        # Mock the responses for _get_metadata calls
        call_count = [0]

        def mock_get_metadata(doc_id, bucket):
            call_count[0] += 1
            if bucket == "extracted":
                return {
                    "num_pages": 5,
                    "extracted_at": "2024-01-01T00:00:00",
                }
            return None

        mock_storage._get_metadata.side_effect = mock_get_metadata
        mock_storage.bucket_extracted = "extracted"
        mock_storage.bucket_documents = "documents"

        response = test_client.get("/api/v1/documents/doc_123/status")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["progress"] == 1.0
        assert data["pages_processed"] == 5

    def test_status_processing(self, test_client, mock_storage):
        """Test status for document still processing."""
        def mock_get_metadata(doc_id, bucket):
            if bucket == "documents":
                return {
                    "uploaded_at": "2024-01-01T00:00:00",
                }
            return None

        mock_storage._get_metadata.side_effect = mock_get_metadata
        mock_storage.bucket_extracted = "extracted"
        mock_storage.bucket_documents = "documents"

        response = test_client.get("/api/v1/documents/doc_123/status")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "processing"
        assert data["progress"] == 0.5

    def test_status_not_found(self, test_client, mock_storage):
        """Test status for non-existent document."""
        mock_storage._get_metadata.return_value = None

        response = test_client.get("/api/v1/documents/nonexistent/status")

        assert response.status_code == 404

    def test_status_failed_from_processing_tracker(self, test_client, mock_storage):
        """Status should expose failed state if tracker payload exists."""
        mock_storage._get_metadata.side_effect = [None, {"document_id": "doc_123"}]
        mock_storage.get_processing_status.return_value = {
            "document_id": "doc_123",
            "status": "failed",
            "progress": 1.0,
            "pages_processed": 0,
            "total_pages": 0,
            "error": "OCR timeout",
        }
        mock_storage.bucket_extracted = "extracted"
        mock_storage.bucket_documents = "documents"

        response = test_client.get("/api/v1/documents/doc_123/status")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failed"
        assert data["error"] == "OCR timeout"


class TestDocumentContent:
    """Tests for /documents/{id}/content endpoint."""

    def test_get_content_success(self, test_client, mock_storage):
        """Test getting extracted content."""
        mock_storage.get_extracted_content.return_value = {
            "markdown": "# Test\n\nContent here",
            "metadata": {
                "num_pages": 2,
                "num_elements": 10,
                "extracted_at": "2024-01-01T00:00:00",
            }
        }
        mock_storage._get_metadata.return_value = {
            "original_filename": "test.pdf",
        }

        response = test_client.get("/api/v1/documents/doc_123/content")

        assert response.status_code == 200
        data = response.json()
        assert data["document_id"] == "doc_123"
        assert data["markdown"] == "# Test\n\nContent here"
        assert data["num_pages"] == 2

    def test_get_content_not_found(self, test_client, mock_storage):
        """Test getting content for non-existent document."""
        mock_storage.get_extracted_content.return_value = None

        response = test_client.get("/api/v1/documents/nonexistent/content")

        assert response.status_code == 404


class TestDocumentLayout:
    """Tests for layout and page rendering endpoints."""

    def test_get_layout_success(self, test_client, mock_storage):
        mock_storage.get_extracted_content.return_value = {
            "markdown": "# Test\n\nContent here",
            "layout": [[{"index": 1, "label": "text", "content": "Budget 1200", "bbox_2d": {"x1": 0.1, "y1": 0.2, "x2": 0.3, "y2": 0.4}}]],
            "metadata": {
                "num_pages": 1,
                "ocr_response": {
                    "data_info": {
                        "pages": [{"width": 1000, "height": 1400}],
                    }
                },
            },
        }
        mock_storage._get_metadata.return_value = {"original_filename": "test.pdf"}

        response = test_client.get("/api/v1/documents/doc_123/layout")

        assert response.status_code == 200
        data = response.json()
        assert data["document_id"] == "doc_123"
        assert data["num_pages"] == 1
        assert data["page_infos"][0]["width"] == 1000

    def test_render_document_page_uses_cache(self, test_client, mock_storage):
        mock_storage._get_metadata.return_value = {"original_filename": "test.pdf"}
        mock_storage.cache_get.return_value = b"cached-png"

        response = test_client.get("/api/v1/documents/doc_123/pages/1/render")

        assert response.status_code == 200
        assert response.content == b"cached-png"


class TestCompareEndpoints:
    """Tests for compare-documents endpoints."""

    def test_compare_suggest_claims(self, test_client, mock_storage):
        mock_storage.get_extracted_content.return_value = {
            "markdown": "Budget 1200 EUR",
            "layout": [],
            "metadata": {"num_pages": 1},
        }
        mock_storage._get_metadata.return_value = {"original_filename": "sample.pdf"}

        class FakeComparePipeline:
            def prepare_document(self, document_id: str, filename: str, markdown: str, layout: list):
                return {"document_id": document_id, "filename": filename, "markdown": markdown}

            def suggest_claims(self, left, right, limit: int = 8):
                assert left["document_id"] == "left-doc"
                assert right["document_id"] == "right-doc"
                return [{"claim": "The monetary terms are identical in both documents."}]

        with patch("app.api.routes.CompareDocumentsPipeline", return_value=FakeComparePipeline()):
            response = test_client.post(
                "/api/v1/compare/suggest-claims",
                json={"left_document_id": "left-doc", "right_document_id": "right-doc", "limit": 4},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert "monetary terms" in data["suggestions"][0]["claim"]

    def test_compare_analyze(self, test_client, mock_storage):
        mock_storage.get_extracted_content.return_value = {
            "markdown": "Budget 1200 EUR",
            "layout": [],
            "metadata": {"num_pages": 1},
        }
        mock_storage._get_metadata.return_value = {"original_filename": "sample.pdf"}

        class FakeComparePipeline:
            def prepare_document(self, document_id: str, filename: str, markdown: str, layout: list):
                return {"document_id": document_id, "filename": filename, "markdown": markdown}

            async def analyze(self, left, right, claims, auto_diff, strategy, index_name, top_k, model):
                assert left["document_id"] == "left-doc"
                assert right["document_id"] == "right-doc"
                assert strategy == "hybrid"
                return {
                    "status": "completed",
                    "issues": [{"issue_id": "issue-1", "claim": "Budget is identical", "verdict": "inconsistent"}],
                    "summary": {"inconsistent_count": 1, "latency_ms": 50},
                    "usage": {"total_tokens": 100},
                }

        with patch("app.api.routes.CompareDocumentsPipeline", return_value=FakeComparePipeline()):
            response = test_client.post(
                "/api/v1/compare/analyze",
                json={
                    "left_document_id": "left-doc",
                    "right_document_id": "right-doc",
                    "claims": ["Budget is identical"],
                    "auto_diff": True,
                    "strategy": "hybrid",
                    "top_k": 5,
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["issues"][0]["issue_id"] == "issue-1"


class TestDocumentDelete:
    """Tests for DELETE /documents/{id} endpoint."""

    def test_delete_success(self, test_client, mock_storage):
        """Test successful document deletion."""
        mock_storage.delete_document.return_value = True

        response = test_client.delete("/api/v1/documents/doc_123")

        assert response.status_code == 200
        assert "deleted successfully" in response.json()["message"]

    def test_delete_not_found(self, test_client, mock_storage):
        """Test deleting non-existent document."""
        mock_storage.delete_document.return_value = False

        response = test_client.delete("/api/v1/documents/nonexistent")

        assert response.status_code == 404


class TestDocumentList:
    """Tests for GET /documents endpoint."""

    def test_list_documents(self, test_client, mock_storage):
        """Test listing all documents."""
        mock_storage.list_documents.return_value = [
            {
                "document_id": "doc_1",
                "filename": "test1.pdf",
                "size_bytes": 1024,
                "uploaded_at": "2024-01-01T00:00:00",
            },
            {
                "document_id": "doc_2",
                "filename": "test2.pdf",
                "size_bytes": 2048,
                "uploaded_at": "2024-01-02T00:00:00",
            },
        ]

        response = test_client.get("/api/v1/documents")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2
        assert len(data["documents"]) == 2


class TestDocumentRetryExtraction:
    """Tests for retry extraction endpoint."""

    def test_retry_extraction_success(self, test_client, mock_storage):
        """Should queue ingestion task for an existing uploaded document."""
        mock_storage.bucket_documents = "documents"
        mock_storage._get_metadata.return_value = {
            "document_id": "doc_123",
            "original_filename": "test.pdf",
            "saved_filename": "test.pdf",
        }

        class _FakeAsyncResult:
            id = "task-abc"

        with patch("workers.tasks.ingest_document.apply_async", return_value=_FakeAsyncResult()) as mock_apply_async:
            response = test_client.post("/api/v1/documents/doc_123/extract/retry")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "queued"
        assert data["document_id"] == "doc_123"
        assert data["task_id"] == "task-abc"
        mock_apply_async.assert_called_once()

    def test_retry_extraction_not_found(self, test_client, mock_storage):
        """Should return 404 when document does not exist in documents bucket."""
        mock_storage.bucket_documents = "documents"
        mock_storage._get_metadata.return_value = None

        response = test_client.post("/api/v1/documents/missing/extract/retry")
        assert response.status_code == 404


class TestDocumentRetryIndex:
    """Tests for retry index endpoint."""

    def test_retry_index_success(self, test_client, mock_storage):
        """Should rebuild evidence units and reindex a processed document."""
        mock_storage.bucket_documents = "documents"
        mock_storage.get_extracted_content.return_value = {
            "markdown": "# Title\n\nBudget 1200 EUR",
            "layout": [[{"content": "Budget 1200 EUR", "label": "paragraph", "index": 0}]],
            "metadata": {"num_pages": 1, "num_elements": 1},
        }
        mock_storage._get_metadata.return_value = {
            "document_id": "doc_123",
            "original_filename": "test.pdf",
        }
        mock_storage.get_processing_status.return_value = {
            "pages_processed": 1,
            "total_pages": 1,
        }

        class FakePipeline:
            async def index_evidence_units(self, evidence_units, index_name: str):
                assert index_name == "contracts"
                assert len(evidence_units) == 1
                return {
                    "status": "completed",
                    "index_name": index_name,
                    "indexed_count": 1,
                }

        with patch("app.api.routes.SearchPipeline", return_value=FakePipeline()):
            response = test_client.post(
                "/api/v1/documents/doc_123/index/retry",
                json={"index_name": "contracts"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["document_id"] == "doc_123"
        assert data["index_name"] == "contracts"
        assert data["indexed_count"] == 1
        mock_storage.set_processing_status.assert_called()

    def test_retry_index_not_found(self, test_client, mock_storage):
        """Should return 404 when extracted content does not exist."""
        mock_storage.get_extracted_content.return_value = None

        response = test_client.post("/api/v1/documents/missing/index/retry")
        assert response.status_code == 404


class TestInfoEndpoint:
    """Tests for /info endpoint."""

    def test_info(self, test_client, mock_storage):
        """Test getting API information."""
        response = test_client.get("/api/v1/info")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Docs Regex API"
        assert data["version"] == "0.1.0"
        assert data["features"]["ocr"] is True
        assert data["storage"]["type"] == "MinIO S3"
        assert "endpoints" in data


class TestSearchEndpoints:
    """Tests for search API endpoints."""

    def test_search_documents(self, test_client, mock_storage, mock_ocr):
        """Search endpoint should return pipeline results."""

        class FakePipeline:
            async def run(self, query: str, index_name: str, top_k: int, strategy: str):
                assert query == "deadline"
                assert index_name == "contracts"
                assert top_k == 3
                assert strategy == "hybrid"
                return {
                    "status": "completed",
                    "query": query,
                    "index_name": index_name,
                    "strategy": strategy,
                    "count": 1,
                    "results": [{"id": "ev-1", "score": 0.98}],
                }

        with patch("app.api.routes.SearchPipeline", return_value=FakePipeline()):
            response = test_client.post(
                "/api/v1/search",
                json={"query": "deadline", "index_name": "contracts", "top_k": 3},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["count"] == 1
        assert data["results"][0]["id"] == "ev-1"

    def test_index_evidence(self, test_client, mock_storage, mock_ocr):
        """Index endpoint should return indexed count."""

        class FakePipeline:
            async def index_evidence_units(self, evidence_units, index_name: str):
                assert index_name == "contracts"
                assert len(evidence_units) == 2
                return {
                    "status": "completed",
                    "index_name": index_name,
                    "indexed_count": 2,
                    "provider_response": {"status": "ok"},
                }

        payload = {
            "index_name": "contracts",
            "evidence_units": [
                {
                    "evidence_id": "ev-1",
                    "document_id": "doc-1",
                    "content": "Clause A",
                    "source_type": "text_span",
                    "page_number": 1,
                    "metadata": {"section": "A"},
                },
                {
                    "evidence_id": "ev-2",
                    "document_id": "doc-1",
                    "content": "Clause B",
                    "source_type": "text_span",
                    "page_number": 2,
                    "metadata": {"section": "B"},
                },
            ],
        }

        with patch("app.api.routes.SearchPipeline", return_value=FakePipeline()):
            response = test_client.post("/api/v1/search/index", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["index_name"] == "contracts"
        assert data["indexed_count"] == 2


class TestDetectEndpoint:
    """Tests for detection endpoint."""

    def test_detect_success(self, test_client, mock_storage, mock_ocr):
        """Detection endpoint should return pipeline decision."""
        mock_storage.get_extracted_content.return_value = {
            "markdown": "Budget 900 EUR",
            "layout": [],
            "metadata": {"num_pages": 1},
        }

        class FakeDetectionPipeline:
            def run(self, document_id: str, claims: list[str], markdown: str, layout: list):
                assert document_id == "doc_123"
                assert claims == ["Budget 1200 EUR"]
                assert "900 EUR" in markdown
                return {
                    "status": "completed",
                    "document_id": document_id,
                    "claims_count": 1,
                    "conflict_count": 1,
                    "severity": "high",
                    "recommendation": "Escalate to reviewer before validation.",
                    "llm_required": True,
                    "results": [{"claim": claims[0], "conflicts": [{"type": "amount_conflict"}]}],
                }

        with patch("app.api.routes.DetectionPipeline", return_value=FakeDetectionPipeline()):
            response = test_client.post(
                "/api/v1/detect",
                json={"document_id": "doc_123", "claims": ["Budget 1200 EUR"]},
            )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "completed"
        assert payload["severity"] == "high"
        assert payload["conflict_count"] == 1

    def test_detect_missing_document(self, test_client, mock_storage, mock_ocr):
        """Detection should return 404 if extracted content is absent."""
        mock_storage.get_extracted_content.return_value = None
        response = test_client.post(
            "/api/v1/detect",
            json={"document_id": "missing", "claims": ["x"]},
        )
        assert response.status_code == 404


class TestLLMEndpoint:
    """Tests for LLM analyze endpoint."""

    def test_llm_analyze_success(self, test_client, mock_storage, mock_ocr):
        class FakeLiteLLMClient:
            def analyze_sync(self, prompt: str, model: str | None = None, temperature: float = 0.0, max_tokens: int | None = None):
                assert "budget" in prompt.lower()
                return {
                    "status": "completed",
                    "model": model or "openrouter/default",
                    "content": "analysis",
                    "usage": {"prompt_tokens": 3, "completion_tokens": 2},
                }

        with patch("app.api.routes.LiteLLMClient", return_value=FakeLiteLLMClient()):
            response = test_client.post(
                "/api/v1/llm/analyze",
                json={"prompt": "Budget check", "model": "openrouter/test-model"},
            )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "completed"
        assert payload["model"] == "openrouter/test-model"
        assert payload["content"] == "analysis"

    def test_llm_analyze_document_success(self, test_client, mock_storage, mock_ocr):
        mock_storage.get_extracted_content.return_value = {
            "filename": "sample.pdf",
            "markdown": "Budget source: 900 EUR.",
            "layout": [[{"index": 0, "label": "text", "content": "Budget source: 900 EUR."}]],
        }

        class FakeSearchPipeline:
            async def run(self, query: str, index_name: str, top_k: int, strategy: str):
                assert query == "Budget est 1200 EUR."
                return {
                    "status": "completed",
                    "results": [
                        {"id": "doc-1:p1:e0", "score": 0.9, "metadata": {"page_number": 1}}
                    ],
                }

        class FakeLiteLLMClient:
            def analyze_sync(self, prompt: str, model: str | None = None, temperature: float = 0.0, max_tokens: int | None = None):
                assert "CLAIM" in prompt
                assert "EVIDENCE" in prompt
                return {
                    "status": "completed",
                    "model": model or "openrouter/default",
                    "content": '{"verdict":"inconsistent","confidence":0.9}',
                    "usage": {"prompt_tokens": 30, "completion_tokens": 8},
                }

        with patch("app.api.routes.SearchPipeline", return_value=FakeSearchPipeline()):
            with patch("app.api.routes.LiteLLMClient", return_value=FakeLiteLLMClient()):
                response = test_client.post(
                    "/api/v1/llm/analyze/document",
                    json={
                        "document_id": "doc-1",
                        "claim": "Budget est 1200 EUR.",
                        "model": "openrouter/test-model",
                        "index_name": "default",
                        "strategy": "hybrid",
                        "top_k": 5,
                    },
                )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "completed"
        assert payload["model"] == "openrouter/test-model"
        assert payload["document_id"] == "doc-1"
        assert payload["evidence_count"] == 1
        assert payload["evidence"][0]["id"] == "doc-1:p1:e0"

    def test_llm_analyze_document_missing_document(self, test_client, mock_storage, mock_ocr):
        mock_storage.get_extracted_content.return_value = None
        response = test_client.post(
            "/api/v1/llm/analyze/document",
            json={"document_id": "missing", "claim": "x"},
        )
        assert response.status_code == 404

    def test_llm_analyze_document_reindexes_and_falls_back_when_search_is_empty(self, test_client, mock_storage, mock_ocr):
        mock_storage.get_extracted_content.return_value = {
            "filename": "sample.pdf",
            "markdown": "Budget source: 900 EUR.\n\nApproved budget: 1200 EUR.",
            "layout": [[{"index": 0, "label": "text", "content": "Budget source: 900 EUR."}]],
        }

        class FakeSearchPipeline:
            def __init__(self):
                self.run_calls = 0
                self.index_calls = 0

            async def run(self, query: str, index_name: str, top_k: int, strategy: str):
                self.run_calls += 1
                return {"status": "completed", "results": []}

            async def index_evidence_units(self, evidence_units, index_name: str):
                self.index_calls += 1
                assert len(evidence_units) >= 2
                assert index_name == "default"
                return {"status": "completed", "indexed_count": len(evidence_units), "index_name": index_name}

        class FakeLiteLLMClient:
            def analyze_sync(self, prompt: str, model: str | None = None, temperature: float = 0.0, max_tokens: int | None = None):
                assert "Approved budget: 1200 EUR." in prompt
                return {
                    "status": "completed",
                    "model": model or "openrouter/default",
                    "content": '{"verdict":"inconsistent","confidence":0.8}',
                    "usage": {"prompt_tokens": 20, "completion_tokens": 6},
                }

        fake_pipeline = FakeSearchPipeline()
        with patch("app.api.routes.SearchPipeline", return_value=fake_pipeline):
            with patch("app.api.routes.LiteLLMClient", return_value=FakeLiteLLMClient()):
                response = test_client.post(
                    "/api/v1/llm/analyze/document",
                    json={
                        "document_id": "doc-1",
                        "claim": "Approved budget is 1200 EUR.",
                        "index_name": "default",
                        "strategy": "hybrid",
                        "top_k": 5,
                    },
                )

        assert response.status_code == 200
        payload = response.json()
        assert payload["evidence_count"] >= 1
        assert payload["evidence"][0]["metadata"]["retrieval_mode"].startswith("document_local_fallback")
        assert fake_pipeline.index_calls == 1


class TestEvalEndpoints:
    """Tests for evaluation endpoints."""

    def test_eval_detection(self, test_client, mock_storage, mock_ocr):
        response = test_client.post(
            "/api/v1/eval/detection",
            json={"gold_labels": [True, False, True], "predicted_labels": [True, False, False]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["precision"] == 1.0
        assert data["recall"] == 0.5

    def test_eval_economics(self, test_client, mock_storage, mock_ocr):
        response = test_client.post(
            "/api/v1/eval/economics",
            json={"runs": [{"prompt_tokens": 10, "completion_tokens": 5, "latency_ms": 100}]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_tokens"] == 15.0

    def test_eval_search_baseline(self, test_client, mock_storage, mock_ocr):
        response = test_client.post(
            "/api/v1/eval/search",
            json={
                "strategy": "baseline",
                "top_k": 5,
                "corpus": [
                    {"id": "doc-1", "text": "delivery deadline approved"},
                    {"id": "doc-2", "text": "budget only"},
                ],
                "samples": [
                    {
                        "sample_id": "s1",
                        "query": "delivery deadline",
                        "relevant_ids": ["doc-1"],
                        "relevance_by_id": {"doc-1": 1.0},
                        "index_name": "default",
                    }
                ],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["strategy"] == "baseline"
        assert data["samples"] == 1

    def test_eval_find_experiment(self, test_client, mock_storage, mock_ocr):
        class FakeRunner:
            async def run_find_experiment(
                self,
                dataset_name: str,
                split: str,
                max_samples: int,
                index_name: str,
                top_k: int,
                strategies: list[str],
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
                return {
                    "dataset_name": "kensho/FIND",
                    "split": split,
                    "samples_count": 1,
                    "corpus_count": 1,
                    "comparison": {"best_strategy_by_recall": "baseline"},
                }

        class FakeHistoryRepo:
            def save_run(self, experiment_type: str, config: dict, result: dict):
                assert experiment_type == "find"
                assert config["split"] == "validation"
                assert result["dataset_name"] == "kensho/FIND"
                return {"run_id": "run-123", "created_at": "2026-03-26T00:00:00+00:00"}

        with patch("app.api.routes.EvaluationRunner", return_value=FakeRunner()), patch(
            "app.api.routes.ExperimentHistoryRepository",
            return_value=FakeHistoryRepo(),
        ):
            response = test_client.post(
                "/api/v1/eval/experiments/find",
                json={
                    "split": "validation",
                    "dataset_name": "kensho/FIND",
                    "max_samples": 10,
                    "index_name": "default",
                    "top_k": 5,
                    "strategies": ["baseline", "semantic"],
                    "streaming": True,
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["dataset_name"] == "kensho/FIND"
        assert data["comparison"]["best_strategy_by_recall"] == "baseline"
        assert data["run_id"] == "run-123"

    def test_eval_find_experiment_returns_422_when_schema_mismatch(self, test_client, mock_storage, mock_ocr):
        class FakeRunner:
            async def run_find_experiment(
                self,
                dataset_name: str,
                split: str,
                max_samples: int,
                index_name: str,
                top_k: int,
                strategies: list[str],
                streaming: bool,
                cache_dir: str | None,
                max_query_chars: int,
            ):
                raise FindEvalPackError("schema_mismatch", "Rows loaded but invalid schema")

        with patch("app.api.routes.EvaluationRunner", return_value=FakeRunner()):
            response = test_client.post(
                "/api/v1/eval/experiments/find",
                json={
                    "dataset_name": "kensho/FIND",
                    "split": "validation",
                    "max_samples": 10,
                    "index_name": "default",
                    "top_k": 5,
                    "strategies": ["baseline", "semantic"],
                    "streaming": True,
                },
            )

        assert response.status_code == 422
        data = response.json()
        assert data["detail"].startswith("[schema_mismatch]")

    def test_eval_find_experiment_returns_424_when_dataset_access_fails(self, test_client, mock_storage, mock_ocr):
        class FakeRunner:
            async def run_find_experiment(
                self,
                dataset_name: str,
                split: str,
                max_samples: int,
                index_name: str,
                top_k: int,
                strategies: list[str],
                streaming: bool,
                cache_dir: str | None,
                max_query_chars: int,
            ):
                raise FindEvalPackError("dataset_access_error", "Unable to load gated dataset")

        with patch("app.api.routes.EvaluationRunner", return_value=FakeRunner()):
            response = test_client.post(
                "/api/v1/eval/experiments/find",
                json={
                    "dataset_name": "kensho/FIND",
                    "split": "validation",
                    "max_samples": 10,
                    "index_name": "default",
                    "top_k": 5,
                    "strategies": ["baseline", "semantic"],
                    "streaming": True,
                },
            )

        assert response.status_code == 424
        data = response.json()
        assert data["detail"].startswith("[dataset_access_error]")

    def test_list_experiment_history(self, test_client, mock_storage, mock_ocr):
        class FakeHistoryRepo:
            def list_runs(self, limit: int = 20):
                assert limit == 20
                return [
                    {
                        "run_id": "run-1",
                        "created_at": "2026-03-26T00:00:00+00:00",
                        "experiment_type": "find",
                        "dataset_name": "kensho/FIND",
                        "split": "validation",
                        "index_name": "default",
                        "best_strategy": "rg",
                        "strategies": ["rg"],
                        "samples_count": 10,
                        "corpus_count": 20,
                        "summary_metrics": {"avg_recall_at_k": 0.2},
                    }
                ]

        with patch("app.api.routes.ExperimentHistoryRepository", return_value=FakeHistoryRepo()):
            response = test_client.get("/api/v1/eval/experiments/history")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["runs"][0]["run_id"] == "run-1"

    def test_get_experiment_history_run(self, test_client, mock_storage, mock_ocr):
        class FakeHistoryRepo:
            def get_run(self, run_id: str):
                assert run_id == "run-1"
                return {"run_id": run_id, "result": {"comparison": {"reports": {}}}}

        with patch("app.api.routes.ExperimentHistoryRepository", return_value=FakeHistoryRepo()):
            response = test_client.get("/api/v1/eval/experiments/history/run-1")

        assert response.status_code == 200
        assert response.json()["run_id"] == "run-1"
