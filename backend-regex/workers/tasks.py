"""
Tâches asynchrones Celery pour le traitement en arrière-plan.

Phase 2 : ingest_document (OCR + parsing + MinIO storage)
Phase 3 : process_search (recherche avec NextPlaid)
Phase 4 : run_detection (détection d'incohérences)
Phase 5 : analyze_with_llm (analyse via LLM)
"""

import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

import httpx
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded

from workers.celery_app import celery_app
from app.ingest import get_ocr_client, get_minio_storage
from app.config import get_settings
from app.detect import DetectionPipeline
from app.eval import EvaluationRunner, SearchEvalSample
from app.llm import LiteLLMClient
from app.monitor import get_langfuse_tracker, start_span
from app.search.pipeline import SearchPipeline
from app.search import build_evidence_units_from_ocr

logger = logging.getLogger(__name__)
settings = get_settings()
tracker = get_langfuse_tracker()


def _parse_s3_uri(file_path: str) -> tuple[str, str]:
    """Parse an S3 URI into bucket and key."""
    if not file_path.startswith("s3://"):
        raise ValueError(f"Not an S3 URI: {file_path}")

    without_scheme = file_path[len("s3://"):]
    if "/" not in without_scheme:
        raise ValueError(f"Invalid S3 URI (missing key): {file_path}")

    bucket, key = without_scheme.split("/", 1)
    if not bucket or not key:
        raise ValueError(f"Invalid S3 URI: {file_path}")

    return bucket, key


# ============================================================================
# Base Task with Error Handling
# ============================================================================

class BaseTaskWithRetry(Task):
    """Base task class with consistent error handling and logging."""

    autoretry_for = (Exception,)
    retry_backoff = True
    retry_kwargs = {"max_retries": 3}
    retry_jitter = True

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Handle task failure."""
        logger.error(
            f"Task {self.name} [{task_id}] failed: {exc}",
            exc_info=einfo,
            extra={"task_id": task_id, "args": args, "kwargs": kwargs}
        )

    def on_success(self, retval, task_id, args, kwargs):
        """Handle task success."""
        logger.info(
            f"Task {self.name} [{task_id}] completed successfully",
            extra={"task_id": task_id, "result": retval}
        )


# ============================================================================
# Phase 2: Document Ingestion (OCR + Parsing + MinIO)
# ============================================================================

@celery_app.task(
    name="workers.tasks.ingest_document",
    base=BaseTaskWithRetry,
    bind=True,
    soft_time_limit=300,  # 5 minutes
    time_limit=600,       # 10 minutes hard limit
)
def ingest_document(
    self,
    document_id: str,
    file_path: str,
    filename: str,
    is_url: bool = False,
) -> dict:
    """
    Ingest un document : OCR + parsing + sauvegarde MinIO.

    Args:
        document_id: Unique document identifier
        file_path: Path to file, S3 URI, or URL
        filename: Original filename
        is_url: True if file_path is a URL

    Returns:
        Dict with status, extracted content, and metadata
    """
    logger.info(f"Starting ingestion for document {document_id}: {filename}")
    temp_local_path: Optional[str] = None
    storage = None

    try:
        # Initialize clients
        ocr_client = get_ocr_client()
        storage = get_minio_storage()
        storage.set_processing_status(
            document_id=document_id,
            status="processing",
            progress=0.1,
            details={"stage": "starting"},
        )

        # Check if file_path is S3 URI
        if file_path.startswith("s3://"):
            bucket, key = _parse_s3_uri(file_path)
            logger.info(f"S3 file detected: {bucket}/{key}")

            if "/" in key:
                key_document_id, saved_filename = key.split("/", 1)
            else:
                key_document_id, saved_filename = document_id, key

            if key_document_id != document_id:
                logger.warning(
                    "S3 URI document_id mismatch: path=%s arg=%s",
                    key_document_id,
                    document_id,
                )

            file_bytes = storage.get_file_content(key_document_id, saved_filename)
            if file_bytes is None:
                storage.set_processing_status(
                    document_id=document_id,
                    status="failed",
                    progress=1.0,
                    error=f"Unable to load file from MinIO: s3://{bucket}/{key}",
                    details={"stage": "load_source"},
                )
                return {
                    "status": "error",
                    "document_id": document_id,
                    "error": f"Unable to load file from MinIO: s3://{bucket}/{key}",
                }

            suffix = Path(saved_filename).suffix or Path(filename).suffix or ".bin"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
                tmp_file.write(file_bytes)
                temp_local_path = tmp_file.name

            file_path = temp_local_path
            is_url = False
            storage.set_processing_status(
                document_id=document_id,
                status="processing",
                progress=0.25,
                details={"stage": "source_loaded"},
            )

        # Run OCR (handles chunking for large PDFs automatically)
        import asyncio
        storage.set_processing_status(
            document_id=document_id,
            status="processing",
            progress=0.45,
            details={"stage": "ocr_running"},
        )
        response = asyncio.run(ocr_client.parse_document(
            file=file_path,
            is_url=is_url,
            return_crop_images=False,
            need_layout_visualization=False,
        ))

        # Extract key information
        num_pages = len(response.layout_details)
        num_elements = sum(len(page) for page in response.layout_details)
        storage.set_processing_status(
            document_id=document_id,
            status="processing",
            progress=0.7,
            pages_processed=num_pages,
            total_pages=num_pages,
            details={"stage": "ocr_completed"},
        )

        # Save extracted content to MinIO
        storage.save_extracted_content(
            document_id=document_id,
            md_results=response.md_results,
            layout_details=response.layout_details,
            ocr_response=response.model_dump(),
        )
        storage.set_processing_status(
            document_id=document_id,
            status="processing",
            progress=0.85,
            pages_processed=num_pages,
            total_pages=num_pages,
            details={"stage": "extracted_saved"},
        )

        index_status = "skipped"
        indexed_count = 0
        if settings.search_auto_index:
            try:
                evidence_units = build_evidence_units_from_ocr(
                    document_id=document_id,
                    filename=filename,
                    md_results=response.md_results,
                    layout_details=response.layout_details,
                )
                indexed_count = len(evidence_units)

                if evidence_units:
                    search_pipeline = SearchPipeline()
                    asyncio.run(
                        search_pipeline.index_evidence_units(
                            evidence_units=evidence_units,
                            index_name=settings.search_default_index,
                        )
                    )
                    index_status = "completed"
                else:
                    index_status = "empty"
            except Exception as index_error:
                logger.warning(
                    "Search indexing failed for %s: %s",
                    document_id,
                    index_error,
                )
                index_status = "failed"
                storage.set_processing_status(
                    document_id=document_id,
                    status="processing",
                    progress=0.95,
                    pages_processed=num_pages,
                    total_pages=num_pages,
                    details={
                        "stage": "index_failed",
                        "index_error": str(index_error),
                    },
                )

        result = {
            "status": "completed",
            "document_id": document_id,
            "filename": filename,
            "num_pages": num_pages,
            "num_elements": num_elements,
            "model_used": response.model,
            "task_id": response.id,
            "usage": response.usage.model_dump() if response.usage else None,
            "index_status": index_status,
            "indexed_count": indexed_count,
        }
        storage.set_processing_status(
            document_id=document_id,
            status="completed",
            progress=1.0,
            pages_processed=num_pages,
            total_pages=num_pages,
            details={
                "stage": "completed",
                "index_status": index_status,
                "indexed_count": indexed_count,
            },
        )

        logger.info(
            f"Ingestion completed for {document_id}: "
            f"{num_pages} pages, {num_elements} elements extracted"
        )

        return result

    except SoftTimeLimitExceeded:
        logger.warning(f"Task {self.request.id} timed out (soft limit)")
        if storage:
            storage.set_processing_status(
                document_id=document_id,
                status="failed",
                progress=1.0,
                error="OCR processing timed out after 5 minutes",
                details={"stage": "timeout"},
            )
        return {
            "status": "timeout",
            "document_id": document_id,
            "message": "OCR processing timed out after 5 minutes"
        }

    except FileNotFoundError as e:
        logger.error(f"File not found: {file_path}")
        if storage:
            storage.set_processing_status(
                document_id=document_id,
                status="failed",
                progress=1.0,
                error=f"File not found: {e}",
                details={"stage": "file_not_found"},
            )
        return {
            "status": "error",
            "document_id": document_id,
            "error": f"File not found: {e}"
        }

    except ValueError as e:
        logger.error(f"Validation error: {e}")
        if storage:
            storage.set_processing_status(
                document_id=document_id,
                status="failed",
                progress=1.0,
                error=f"Validation error: {e}",
                details={"stage": "validation_error"},
            )
        return {
            "status": "error",
            "document_id": document_id,
            "error": f"Validation error: {e}"
        }

    except httpx.WriteTimeout as e:
        logger.error(f"OCR upload timeout for {document_id}: {e}")
        if storage:
            storage.set_processing_status(
                document_id=document_id,
                status="failed",
                progress=1.0,
                error=(
                    "OCR upload timed out while sending the document to the provider. "
                    "The PDF is likely large/heavy for the current OCR timeout."
                ),
                details={"stage": "ocr_upload_timeout"},
            )
        return {
            "status": "error",
            "document_id": document_id,
            "error": "OCR upload timed out while sending the document to the provider",
        }

    except Exception as e:
        logger.exception(f"Unexpected error during ingestion")
        if storage:
            storage.set_processing_status(
                document_id=document_id,
                status="failed",
                progress=1.0,
                error=str(e),
                details={"stage": "unexpected_error"},
            )
        return {
            "status": "error",
            "document_id": document_id,
            "error": str(e)
        }
    finally:
        if temp_local_path and os.path.exists(temp_local_path):
            os.unlink(temp_local_path)


@celery_app.task(
    name="workers.tasks.ingest_from_url",
    base=BaseTaskWithRetry,
    bind=True,
    soft_time_limit=300,
)
def ingest_from_url(
    self,
    document_id: str,
    url: str,
    filename: Optional[str] = None,
) -> dict:
    """
    Ingest a document from URL (direct OCR without download).

    Args:
        document_id: Unique document identifier
        url: URL to the document (PDF, JPG, PNG)
        filename: Optional filename for records

    Returns:
        Dict with status and extracted content
    """
    filename = filename or url.split("/")[-1]
    return ingest_document(self, document_id, url, filename, is_url=True)


# ============================================================================
# Phase 3: Search (NextPlaid)
# ============================================================================

@celery_app.task(
    name="workers.tasks.process_search",
    base=BaseTaskWithRetry,
    bind=True,
    soft_time_limit=60,
)
def process_search(
    self,
    query: str,
    index_name: str = "default",
    strategy: str = "hybrid",
    top_k: int = 10,
) -> dict:
    """
    Effectue une recherche dans les documents indexés avec NextPlaid.

    Phase 3 - À implémenter
    """
    import asyncio

    pipeline = SearchPipeline()
    return asyncio.run(
        pipeline.run(
            query=query,
            index_name=index_name,
            top_k=top_k,
            strategy=strategy,
        )
    )


# ============================================================================
# Phase 4: Inconsistency Detection
# ============================================================================

@celery_app.task(
    name="workers.tasks.run_detection",
    base=BaseTaskWithRetry,
    bind=True,
    soft_time_limit=180,
)
def run_detection(self, document_id: str, claim_ids: list[str]) -> dict:
    """
    Détecte les incohérences entre claims et preuves.

    Phase 4 - À implémenter
    """
    storage = get_minio_storage()
    extracted = storage.get_extracted_content(document_id)
    if not extracted:
        return {
            "status": "error",
            "document_id": document_id,
            "error": "Document extracted content not found",
            "claim_ids": claim_ids,
        }

    pipeline = DetectionPipeline()
    return pipeline.run(
        document_id=document_id,
        claims=claim_ids,
        markdown=extracted.get("markdown", ""),
        layout=extracted.get("layout", []),
    )


# ============================================================================
# Phase 5: LLM Analysis
# ============================================================================

@celery_app.task(
    name="workers.tasks.analyze_with_llm",
    base=BaseTaskWithRetry,
    bind=True,
    soft_time_limit=120,
)
def analyze_with_llm(self, prompt: str, model: Optional[str] = None) -> dict:
    """
    Analyse un prompt avec un LLM via LiteLLM/OpenRouter.

    Phase 5 - À implémenter
    """
    with start_span("llm.analyze.task", {"model": model or settings.llm_default_model}):
        trace_id = tracker.trace(
            name="llm.analyze",
            input_payload={"prompt": prompt, "model": model or settings.llm_default_model},
        )
        try:
            client = LiteLLMClient()
            response = client.analyze_sync(
                prompt=prompt,
                model=model or settings.llm_default_model,
                temperature=0.0,
                max_tokens=settings.llm_max_tokens,
            )
            tracker.event(
                trace_id=trace_id,
                name="llm.response",
                output={"model": response["model"], "usage": response.get("usage", {})},
            )
            return {
                "status": "completed",
                "model": response["model"],
                "content": response["content"],
                "usage": response.get("usage", {}),
                "trace_id": trace_id,
            }
        except Exception as exc:
            tracker.event(trace_id=trace_id, name="llm.error", output={"error": str(exc)})
            return {
                "status": "error",
                "model": model or settings.llm_default_model,
                "error": str(exc),
                "trace_id": trace_id,
            }


# ============================================================================
# Phase 7: Evaluation Framework
# ============================================================================

@celery_app.task(
    name="workers.tasks.run_eval_search",
    base=BaseTaskWithRetry,
    bind=True,
    soft_time_limit=300,
)
def run_eval_search(
    self,
    samples: list[dict],
    corpus: list[dict],
    strategy: str = "baseline",
    top_k: int = 10,
) -> dict:
    """Run search evaluation asynchronously."""
    import asyncio

    eval_samples = [
        SearchEvalSample(
            sample_id=str(item.get("sample_id", "")),
            query=str(item.get("query", "")),
            relevant_ids={str(v) for v in item.get("relevant_ids", [])},
            relevance_by_id={str(k): float(v) for k, v in item.get("relevance_by_id", {}).items()},
            index_name=str(item.get("index_name", "default")),
        )
        for item in samples
    ]
    runner = EvaluationRunner()
    return asyncio.run(
        runner.evaluate_search(
            samples=eval_samples,
            corpus=corpus,
            strategy=strategy,
            top_k=top_k,
        )
    )


@celery_app.task(
    name="workers.tasks.run_find_experiment",
    base=BaseTaskWithRetry,
    bind=True,
    soft_time_limit=1200,
)
def run_find_experiment(
    self,
    dataset_name: str = "kensho/FIND",
    split: str = "validation",
    max_samples: int = 100,
    index_name: str = "default",
    top_k: int = 10,
    strategies: list[str] | None = None,
    streaming: bool = True,
    cache_dir: str | None = None,
    max_query_chars: int = 8192,
) -> dict:
    """Run phase-8 FIND experiment asynchronously."""
    import asyncio

    runner = EvaluationRunner()
    return asyncio.run(
        runner.run_find_experiment(
            dataset_name=dataset_name,
            split=split,
            max_samples=max_samples,
            index_name=index_name,
            top_k=top_k,
            strategies=strategies,
            streaming=streaming,
            cache_dir=cache_dir,
            max_query_chars=max_query_chars,
        )
    )
