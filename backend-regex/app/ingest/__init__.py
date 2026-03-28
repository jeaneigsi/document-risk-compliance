"""Ingest module - Phase 2.

Ce module contient :
- OCR client (API Z.ai)
- Document parsers (PDF, DOCX, images)
- Storage service (MinIO S3)
- Indexation NextPlaid (Phase 3)
"""

from app.ingest.ocr_client import ZaiOCRClient, get_ocr_client
from app.ingest.s3_storage import MinIOStorage, get_minio_storage
from app.ingest.parser import ParsedDocument, ParsedPage, parse_pdf
from app.ingest.normalizer import NormalizedFields, normalize_text_fields, normalize_metadata
from app.ingest.datasets import (
    load_hf_dataset,
    load_find_dataset,
    load_wikipedia_contradict,
    load_longbench,
)
from app.ingest.models import (
    OCRRequest,
    OCRResponse,
    LayoutElement,
    LayoutLabel,
    BBox2D,
    PageRange,
    PageInfo,
    TokenUsage,
    MAX_PAGES_PER_REQUEST,
)

__all__ = [
    # Client
    "ZaiOCRClient",
    "get_ocr_client",
    # Storage
    "MinIOStorage",
    "get_minio_storage",
    # Parsing
    "ParsedDocument",
    "ParsedPage",
    "parse_pdf",
    # Normalization
    "NormalizedFields",
    "normalize_text_fields",
    "normalize_metadata",
    # Datasets
    "load_hf_dataset",
    "load_find_dataset",
    "load_wikipedia_contradict",
    "load_longbench",
    # Models
    "OCRRequest",
    "OCRResponse",
    "LayoutElement",
    "LayoutLabel",
    "BBox2D",
    "PageRange",
    "PageInfo",
    "TokenUsage",
    "MAX_PAGES_PER_REQUEST",
]
