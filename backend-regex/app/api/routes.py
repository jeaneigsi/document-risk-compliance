"""API routes for document processing - Phase 2: OCR & Parsing with MinIO."""

from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel, Field
from typing import Optional
import logging
import uuid
import json

from app.config import get_settings
from app.detect import DetectionPipeline
from app.eval.baseline import BaselineLexicalRetriever
from app.eval import EvaluationRunner, SearchEvalSample
from app.eval.datasets import FindEvalPackError
from app.eval.history import ExperimentHistoryRepository
from app.ingest import get_ocr_client, get_minio_storage, MAX_PAGES_PER_REQUEST
from app.llm import LiteLLMClient
from app.search import SearchPipeline, EvidenceUnit, build_evidence_units_from_ocr

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/v1", tags=["ingest"])


# ============================================================================
# Request/Response Models
# ============================================================================

class DocumentUploadResponse(BaseModel):
    """Response after document upload."""
    document_id: str
    filename: str
    status: str
    message: str
    size_bytes: int


class DocumentStatusResponse(BaseModel):
    """Status of document processing."""
    document_id: str
    status: str  # pending, processing, completed, failed
    progress: float  # 0.0 to 1.0
    pages_processed: int
    total_pages: int
    error: Optional[str] = None
    index_status: Optional[str] = None
    indexed_count: int = 0
    details: dict = Field(default_factory=dict)


class DocumentRetryExtractionResponse(BaseModel):
    """Response for extraction retry trigger."""
    document_id: str
    filename: str
    status: str
    task_id: Optional[str] = None
    message: str


class DocumentReindexRequest(BaseModel):
    """Request for reindexing a processed document."""
    index_name: str = "default"


class DocumentReindexResponse(BaseModel):
    """Response for document reindex trigger."""
    document_id: str
    filename: str
    status: str
    index_name: str
    indexed_count: int
    message: str


class DocumentContentResponse(BaseModel):
    """Extracted content from a processed document."""
    document_id: str
    filename: str
    markdown: str
    num_pages: int
    num_elements: int
    extracted_at: str


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    components: dict[str, str]


class SearchRequest(BaseModel):
    """Search request payload."""
    query: str
    index_name: str = "default"
    top_k: int = 10
    strategy: str = "hybrid"  # hybrid | semantic | lexical | rg


class SearchResponse(BaseModel):
    """Search response payload."""
    status: str
    query: str
    index_name: str
    strategy: str
    count: int
    results: list[dict]


class IndexEvidenceRequest(BaseModel):
    """Index request for evidence units."""
    index_name: str = "default"
    evidence_units: list[EvidenceUnit]


class IndexEvidenceResponse(BaseModel):
    """Indexing result payload."""
    status: str
    index_name: str
    indexed_count: int


class DetectionRequest(BaseModel):
    """Detection request payload."""
    document_id: str
    claims: list[str]


class DetectionResponse(BaseModel):
    """Detection response payload."""
    status: str
    document_id: str
    claims_count: int
    conflict_count: int
    severity: str
    recommendation: str
    llm_required: bool
    results: list[dict]


class LLMAnalyzeRequest(BaseModel):
    """Direct LLM analyze request."""
    prompt: str
    model: Optional[str] = None


class LLMAnalyzeResponse(BaseModel):
    """Direct LLM analyze response."""
    status: str
    model: str
    content: str
    usage: dict


class LLMAnalyzeDocumentRequest(BaseModel):
    """Document-grounded LLM analysis request."""
    document_id: str
    claim: str
    model: Optional[str] = None
    index_name: str = "default"
    strategy: str = "hybrid"
    top_k: int = 5


class LLMAnalyzeDocumentResponse(BaseModel):
    """Document-grounded LLM analysis response."""
    status: str
    model: str
    document_id: str
    claim: str
    index_name: str
    strategy: str
    evidence_count: int
    evidence: list[dict]
    content: str
    usage: dict


class EvalSearchSampleRequest(BaseModel):
    """One retrieval evaluation sample."""
    sample_id: str
    query: str
    relevant_ids: list[str]
    relevance_by_id: dict[str, float] = Field(default_factory=dict)
    index_name: str = "default"


class EvalSearchRequest(BaseModel):
    """Evaluate a retrieval strategy over provided samples."""
    strategy: str = "baseline"
    top_k: int = 10
    corpus: list[dict] = Field(default_factory=list)
    samples: list[EvalSearchSampleRequest]


class EvalDetectionRequest(BaseModel):
    """Evaluate binary detection labels."""
    gold_labels: list[bool]
    predicted_labels: list[bool]


class EvalEconomicsRequest(BaseModel):
    """Aggregate economics metrics over a list of runs."""
    runs: list[dict]


class EvalFindExperimentRequest(BaseModel):
    """Run phase-8 strategy comparison on FIND subset."""
    dataset_name: str = "kensho/FIND"
    split: str = "validation"
    max_samples: int = 100
    index_name: str = "default"
    top_k: int = 10
    strategies: list[str] = Field(default_factory=lambda: ["baseline", "lexical", "semantic", "hybrid", "rg"])
    streaming: bool = True
    cache_dir: Optional[str] = None
    max_query_chars: int = 8192


class ExperimentHistorySummaryResponse(BaseModel):
    run_id: str
    created_at: str
    experiment_type: str
    dataset_name: str
    split: str
    index_name: str
    best_strategy: str
    strategies: list[str]
    samples_count: int
    corpus_count: int
    summary_metrics: dict


class ExperimentHistoryListResponse(BaseModel):
    count: int
    runs: list[ExperimentHistorySummaryResponse]


# ============================================================================
# Dependencies
# ============================================================================

async def get_minio():
    """Get MinIO storage instance."""
    return get_minio_storage()


# ============================================================================
# Endpoints
# ============================================================================

@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Check API and external services health."""
    ocr_client = get_ocr_client()
    minio_storage = get_minio_storage()

    ocr_healthy = await ocr_client.health_check()
    minio_healthy = minio_storage.health_check()

    return HealthResponse(
        status="healthy" if all([ocr_healthy, minio_healthy]) else "degraded",
        version=settings.app_version,
        components={
            "ocr": "ok" if ocr_healthy else "error",
            "minio": "ok" if minio_healthy else "error",
            "nextplaid": "unknown",  # TODO: Phase 3
            "redis": "unknown",  # TODO: Celery health check
        }
    )


@router.post("/documents/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = None,
):
    """
    Upload a document for OCR and processing.

    Supported formats: PDF, JPG, PNG
    Max file size: 50MB for PDF, 10MB for images

    The document will be:
    1. Stored in MinIO (documents bucket)
    2. Processed by OCR (Z.ai API)
    3. Results stored in MinIO (extracted bucket)
    """
    # Validate file size
    max_size = 50 * 1024 * 1024 if file.filename.endswith(".pdf") else 10 * 1024 * 1024
    content = await file.read()

    if len(content) > max_size:
        raise HTTPException(
            status_code=413,
            detail=f"File too large: {len(content) / (1024*1024):.1f}MB (max {max_size / (1024*1024)}MB)"
        )

    # Validate file type
    allowed_extensions = {".pdf", ".jpg", ".jpeg", ".png"}
    file_ext = "." + file.filename.split(".")[-1].lower() if "." in file.filename else ""

    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file_ext}. Allowed: {sorted(allowed_extensions)}"
        )

    # Generate unique document ID
    document_id = str(uuid.uuid4())

    # Save to MinIO
    try:
        storage = get_minio_storage()
        storage.save_uploaded_file(document_id, file.filename, content)
        if hasattr(storage, "set_processing_status"):
            storage.set_processing_status(
                document_id=document_id,
                status="pending",
                progress=0.0,
                pages_processed=0,
                total_pages=0,
                details={"stage": "uploaded"},
            )
        logger.info(f"Document uploaded to MinIO: {file.filename} -> {document_id}")
    except Exception as e:
        logger.error(f"Failed to save document to MinIO: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to store document: {str(e)}"
        )

    # Trigger background processing
    if background_tasks:
        from workers.tasks import ingest_document
        file_key = f"{document_id}/{storage._sanitize_filename(file.filename)}"
        ingest_document.apply_async(
            args=[document_id, f"s3://{settings.minio_bucket_documents}/{file_key}", file.filename],
            kwargs={"is_url": False}
        )

    return DocumentUploadResponse(
        document_id=document_id,
        filename=file.filename,
        status="pending",
        message="Document uploaded successfully. Processing will start shortly.",
        size_bytes=len(content),
    )


@router.get("/documents/{document_id}/status", response_model=DocumentStatusResponse)
async def get_document_status(document_id: str):
    """Get the processing status of a document."""
    storage = get_minio_storage()

    # Check if document exists
    metadata = storage._get_metadata(document_id, storage.bucket_extracted)
    processing_status = None
    if hasattr(storage, "get_processing_status"):
        candidate = storage.get_processing_status(document_id)
        if isinstance(candidate, dict):
            processing_status = candidate

    if metadata:
        # Processing completed
        details = processing_status.get("details", {}) if isinstance(processing_status, dict) else {}
        return DocumentStatusResponse(
            document_id=document_id,
            status="completed",
            progress=1.0,
            pages_processed=metadata.get("num_pages", 0),
            total_pages=metadata.get("num_pages", 0),
            index_status=details.get("index_status"),
            indexed_count=int(details.get("indexed_count", 0) or 0),
            details=details,
        )
    if processing_status:
        details = processing_status.get("details", {}) if isinstance(processing_status.get("details"), dict) else {}
        return DocumentStatusResponse(
            document_id=document_id,
            status=processing_status.get("status", "processing"),
            progress=float(processing_status.get("progress", 0.0)),
            pages_processed=int(processing_status.get("pages_processed", 0)),
            total_pages=int(processing_status.get("total_pages", 0)),
            error=processing_status.get("error"),
            index_status=details.get("index_status"),
            indexed_count=int(details.get("indexed_count", 0) or 0),
            details=details,
        )
    else:
        # Check if original file exists (pending/processing)
        doc_metadata = storage._get_metadata(document_id, storage.bucket_documents)
        if doc_metadata:
            return DocumentStatusResponse(
                document_id=document_id,
                status="processing",
                progress=0.5,  # In progress
                pages_processed=0,
                total_pages=0,
                details={},
            )
        else:
            raise HTTPException(status_code=404, detail="Document not found")


@router.post("/documents/{document_id}/extract/retry", response_model=DocumentRetryExtractionResponse)
async def retry_document_extraction(document_id: str):
    """Retry OCR extraction for an already uploaded document."""
    storage = get_minio_storage()
    doc_metadata = storage._get_metadata(document_id, storage.bucket_documents)
    if not doc_metadata:
        raise HTTPException(status_code=404, detail="Document not found")

    saved_filename = doc_metadata.get("saved_filename")
    original_filename = doc_metadata.get("original_filename", saved_filename or "unknown")
    if not saved_filename:
        raise HTTPException(status_code=400, detail="Document metadata missing saved filename")

    from workers.tasks import ingest_document

    async_result = ingest_document.apply_async(
        args=[
            document_id,
            f"s3://{settings.minio_bucket_documents}/{document_id}/{saved_filename}",
            original_filename,
        ],
        kwargs={"is_url": False},
    )

    return DocumentRetryExtractionResponse(
        document_id=document_id,
        filename=original_filename,
        status="queued",
        task_id=getattr(async_result, "id", None),
        message="Extraction retry queued",
    )


@router.post("/documents/{document_id}/index/retry", response_model=DocumentReindexResponse)
async def retry_document_index(
    document_id: str,
    payload: DocumentReindexRequest | None = None,
):
    """Rebuild evidence units from extracted content and reindex them."""
    storage = get_minio_storage()
    extracted = storage.get_extracted_content(document_id)
    if not extracted:
        raise HTTPException(status_code=404, detail="Document content not found")

    doc_metadata = storage._get_metadata(document_id, storage.bucket_documents)
    filename = (
        doc_metadata.get("original_filename", "unknown")
        if isinstance(doc_metadata, dict)
        else "unknown"
    )
    index_name = payload.index_name if payload else settings.search_default_index
    index_name = index_name or settings.search_default_index

    evidence_units = build_evidence_units_from_ocr(
        document_id=document_id,
        filename=filename,
        md_results=extracted.get("markdown", ""),
        layout_details=extracted.get("layout", []),
    )
    if not evidence_units:
        raise HTTPException(status_code=422, detail="No evidence units could be built from extracted content")

    pipeline = SearchPipeline()
    result = await pipeline.index_evidence_units(
        evidence_units=evidence_units,
        index_name=index_name,
    )

    if hasattr(storage, "set_processing_status"):
        existing = storage.get_processing_status(document_id) if hasattr(storage, "get_processing_status") else {}
        pages_processed = int((existing or {}).get("pages_processed", 0))
        total_pages = int((existing or {}).get("total_pages", 0))
        storage.set_processing_status(
            document_id=document_id,
            status="completed",
            progress=1.0,
            pages_processed=pages_processed,
            total_pages=total_pages,
            details={
                "stage": "reindexed",
                "index_name": index_name,
                "indexed_count": len(evidence_units),
            },
        )

    return DocumentReindexResponse(
        document_id=document_id,
        filename=filename,
        status="completed",
        index_name=index_name,
        indexed_count=int(result.get("indexed_count", len(evidence_units))),
        message="Document reindexed successfully",
    )


@router.get("/documents/{document_id}/content", response_model=DocumentContentResponse)
async def get_document_content(document_id: str):
    """Get the extracted content (Markdown + layout) of a processed document."""
    storage = get_minio_storage()
    content = storage.get_extracted_content(document_id)

    if not content:
        raise HTTPException(status_code=404, detail="Document content not found")

    # Get original filename
    doc_metadata = storage._get_metadata(document_id, storage.bucket_documents)
    filename = doc_metadata.get("original_filename", "unknown") if doc_metadata else "unknown"

    return DocumentContentResponse(
        document_id=document_id,
        filename=filename,
        markdown=content["markdown"],
        num_pages=content["metadata"].get("num_pages", 0),
        num_elements=content["metadata"].get("num_elements", 0),
        extracted_at=content["metadata"].get("extracted_at", ""),
    )


@router.delete("/documents/{document_id}")
async def delete_document(document_id: str):
    """Delete a document and its associated data from MinIO."""
    storage = get_minio_storage()
    deleted = storage.delete_document(document_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")

    return {"message": f"Document {document_id} deleted successfully"}


@router.get("/documents")
async def list_documents():
    """List all stored documents."""
    storage = get_minio_storage()
    documents = storage.list_documents()
    return {"documents": documents, "count": len(documents)}


@router.post("/search", response_model=SearchResponse, tags=["search"])
async def search_documents(payload: SearchRequest):
    """Search indexed evidence/document chunks."""
    pipeline = SearchPipeline()
    result = await pipeline.run(
        query=payload.query,
        index_name=payload.index_name,
        top_k=payload.top_k,
        strategy=payload.strategy,
    )
    return SearchResponse(**result)


@router.post("/search/index", response_model=IndexEvidenceResponse, tags=["search"])
async def index_evidence(payload: IndexEvidenceRequest):
    """Index evidence units into NextPlaid."""
    pipeline = SearchPipeline()
    result = await pipeline.index_evidence_units(
        evidence_units=payload.evidence_units,
        index_name=payload.index_name,
    )
    return IndexEvidenceResponse(
        status=result["status"],
        index_name=result["index_name"],
        indexed_count=result["indexed_count"],
    )


@router.post("/detect", response_model=DetectionResponse, tags=["detect"])
async def detect_inconsistencies(payload: DetectionRequest):
    """Run inconsistency detection on a processed document."""
    storage = get_minio_storage()
    extracted = storage.get_extracted_content(payload.document_id)
    if not extracted:
        raise HTTPException(status_code=404, detail="Document content not found")

    pipeline = DetectionPipeline()
    result = pipeline.run(
        document_id=payload.document_id,
        claims=payload.claims,
        markdown=extracted.get("markdown", ""),
        layout=extracted.get("layout", []),
    )
    return DetectionResponse(**result)


@router.post("/llm/analyze", response_model=LLMAnalyzeResponse, tags=["llm"])
async def llm_analyze(payload: LLMAnalyzeRequest):
    """Analyze arbitrary prompt using LiteLLM/OpenRouter."""
    client = LiteLLMClient()
    result = client.analyze_sync(
        prompt=payload.prompt,
        model=payload.model,
        temperature=0.0,
        max_tokens=settings.llm_max_tokens,
    )
    return LLMAnalyzeResponse(
        status=result["status"],
        model=result["model"],
        content=result["content"],
        usage=result.get("usage", {}),
    )


@router.post("/llm/analyze/document", response_model=LLMAnalyzeDocumentResponse, tags=["llm"])
async def llm_analyze_document(payload: LLMAnalyzeDocumentRequest):
    """Analyze a claim using document-grounded evidence retrieval."""
    storage = get_minio_storage()
    extracted = storage.get_extracted_content(payload.document_id)
    if not extracted:
        raise HTTPException(status_code=404, detail="Document content not found")

    # Build id->text map from extracted OCR content so semantic hits can be materialized.
    units = build_evidence_units_from_ocr(
        document_id=payload.document_id,
        filename=extracted.get("filename", "document"),
        md_results=extracted.get("markdown", ""),
        layout_details=extracted.get("layout", []),
    )
    content_by_id = {unit.evidence_id: unit.content for unit in units}

    search_pipeline = SearchPipeline()

    async def _run_indexed_search() -> dict:
        return await search_pipeline.run(
            query=payload.claim,
            index_name=payload.index_name,
            top_k=payload.top_k,
            strategy=payload.strategy,
        )

    retrieval = await _run_indexed_search()
    retrieval_mode = "indexed"

    if not retrieval.get("results") and units:
        logger.info(
            "llm.document.retrieval_empty document_id=%s strategy=%s index_name=%s; reindexing and retrying",
            payload.document_id,
            payload.strategy,
            payload.index_name,
        )
        await search_pipeline.index_evidence_units(
            evidence_units=units,
            index_name=payload.index_name,
        )
        retrieval = await _run_indexed_search()
        retrieval_mode = "indexed_after_reindex"

    if not retrieval.get("results") and units:
        docs = [
            {
                "id": unit.evidence_id,
                "text": unit.content,
                "metadata": {
                    "document_id": unit.document_id,
                    "source_type": unit.source_type,
                    "page_number": unit.page_number,
                    **unit.metadata,
                },
            }
            for unit in units
        ]
        local_results = BaselineLexicalRetriever().search(
            query=payload.claim,
            corpus=docs,
            top_k=payload.top_k,
        )
        retrieval = {
            "status": "completed",
            "results": local_results,
        }
        retrieval_mode = "document_local_fallback:baseline"

    evidence_rows: list[dict] = []
    for row in retrieval.get("results", []):
        row_id = str(row.get("id") or "")
        text = str(row.get("text") or content_by_id.get(row_id) or "").strip()
        evidence_rows.append(
            {
                "id": row_id,
                "score": float(row.get("score", 0.0)),
                "text": text,
                "metadata": {
                    **(row.get("metadata", {}) or {}),
                    "retrieval_mode": retrieval_mode,
                },
            }
        )

    evidence_lines = []
    for i, item in enumerate(evidence_rows, start=1):
        snippet = item.get("text", "")
        if not snippet:
            snippet = f"(no_text_available) metadata={json.dumps(item.get('metadata', {}), ensure_ascii=False)}"
        evidence_lines.append(f"[E{i}] id={item.get('id')} score={item.get('score')}\n{snippet}")

    grounded_prompt = (
        "You are a compliance analyst.\n"
        "Task: assess whether the CLAIM is consistent with the EVIDENCE.\n"
        "Rules:\n"
        "- Use only provided evidence.\n"
        "- If evidence is insufficient, say insufficient_evidence.\n"
        "- Return strict JSON with keys: verdict, confidence, rationale, evidence_used_ids, missing_information.\n\n"
        f"CLAIM:\n{payload.claim}\n\n"
        f"EVIDENCE:\n{chr(10).join(evidence_lines) if evidence_lines else '(none)'}\n"
    )

    client = LiteLLMClient()
    result = client.analyze_sync(
        prompt=grounded_prompt,
        model=payload.model,
        temperature=0.0,
        max_tokens=settings.llm_max_tokens,
    )

    return LLMAnalyzeDocumentResponse(
        status=result["status"],
        model=result["model"],
        document_id=payload.document_id,
        claim=payload.claim,
        index_name=payload.index_name,
        strategy=payload.strategy,
        evidence_count=len(evidence_rows),
        evidence=evidence_rows,
        content=result["content"],
        usage=result.get("usage", {}),
    )


@router.post("/eval/search", tags=["eval"])
async def evaluate_search(payload: EvalSearchRequest):
    """Run phase-7 retrieval evaluation metrics."""
    runner = EvaluationRunner()
    samples = [
        SearchEvalSample(
            sample_id=item.sample_id,
            query=item.query,
            relevant_ids=set(item.relevant_ids),
            relevance_by_id=item.relevance_by_id,
            index_name=item.index_name,
        )
        for item in payload.samples
    ]
    return await runner.evaluate_search(
        samples=samples,
        corpus=payload.corpus,
        strategy=payload.strategy,
        top_k=payload.top_k,
    )


@router.post("/eval/detection", tags=["eval"])
async def evaluate_detection(payload: EvalDetectionRequest):
    """Run phase-7 detection metrics (precision/recall/f1)."""
    runner = EvaluationRunner()
    return runner.evaluate_detection(
        gold_labels=payload.gold_labels,
        predicted_labels=payload.predicted_labels,
    )


@router.post("/eval/economics", tags=["eval"])
async def evaluate_economics(payload: EvalEconomicsRequest):
    """Run phase-7 economics aggregation (tokens/cost/latency)."""
    runner = EvaluationRunner()
    return runner.evaluate_economics(payload.runs)


@router.post("/eval/experiments/find", tags=["eval"])
async def eval_find_experiment(payload: EvalFindExperimentRequest):
    """Run phase-8 strategy comparison on FIND with streaming-friendly defaults."""
    runner = EvaluationRunner()
    try:
        result = await runner.run_find_experiment(
            dataset_name=payload.dataset_name,
            split=payload.split,
            max_samples=payload.max_samples,
            index_name=payload.index_name,
            top_k=payload.top_k,
            strategies=payload.strategies,
            streaming=payload.streaming,
            cache_dir=payload.cache_dir,
            max_query_chars=payload.max_query_chars,
        )
        history = ExperimentHistoryRepository().save_run(
            experiment_type="find",
            config=payload.model_dump(),
            result=result,
        )
        return {
            **result,
            "run_id": history["run_id"],
            "created_at": history["created_at"],
        }
    except FindEvalPackError as exc:
        if exc.code == "dataset_access_error":
            status_code = 424
        elif exc.code == "empty_split":
            status_code = 422
        else:
            status_code = 422
        raise HTTPException(
            status_code=status_code,
            detail=f"[{exc.code}] {exc.message}",
        ) from exc


@router.get("/eval/experiments/history", response_model=ExperimentHistoryListResponse, tags=["eval"])
async def list_experiment_history(limit: int = 20):
    repo = ExperimentHistoryRepository()
    runs = repo.list_runs(limit=limit)
    return {
        "count": len(runs),
        "runs": runs,
    }


@router.get("/eval/experiments/history/summary", tags=["eval"])
async def get_experiment_history_summary():
    return ExperimentHistoryRepository().get_summary()


@router.get("/eval/experiments/history/{run_id}", tags=["eval"])
async def get_experiment_history_run(run_id: str):
    run = ExperimentHistoryRepository().get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Experiment run not found")
    return run


# ============================================================================
# Info Endpoints
# ============================================================================

@router.get("/info")
async def api_info():
    """Get API information and configuration."""
    storage = get_minio_storage()

    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "features": {
            "ocr": True,
            "max_pages_per_request": MAX_PAGES_PER_REQUEST,
            "supported_formats": ["PDF", "JPG", "PNG"],
            "storage": "MinIO S3",
        },
        "storage": {
            "type": "MinIO S3",
            "endpoint": settings.minio_endpoint,
            "buckets": {
                "documents": settings.minio_bucket_documents,
                "extracted": settings.minio_bucket_extracted,
                "cache": settings.minio_bucket_cache,
            }
        },
        "endpoints": {
            "health": "/api/v1/health",
            "upload": "/api/v1/documents/upload",
            "list": "/api/v1/documents",
            "status": "/api/v1/documents/{document_id}/status",
            "content": "/api/v1/documents/{document_id}/content",
            "retry_extract": "/api/v1/documents/{document_id}/extract/retry",
            "retry_index": "/api/v1/documents/{document_id}/index/retry",
            "delete": "/api/v1/documents/{document_id}",
            "search": "/api/v1/search",
            "index": "/api/v1/search/index",
            "detect": "/api/v1/detect",
            "llm_analyze": "/api/v1/llm/analyze",
            "eval_search": "/api/v1/eval/search",
            "eval_detection": "/api/v1/eval/detection",
            "eval_economics": "/api/v1/eval/economics",
            "eval_find_experiment": "/api/v1/eval/experiments/find",
        }
    }
