"""Evidence units used for retrieval and inconsistency detection."""

import re
from typing import Any

from pydantic import BaseModel, Field


class EvidenceUnit(BaseModel):
    """A single reusable evidence unit."""

    evidence_id: str
    document_id: str
    content: str
    source_type: str = "text_span"
    page_number: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


def map_find_to_evidence_units(record: dict, document_id: str) -> list[EvidenceUnit]:
    """Map a FIND record to evidence units using `evidence_dicts.spans`."""

    units: list[EvidenceUnit] = []
    evidence_dicts = record.get("evidence_dicts") or []

    for e_idx, evidence in enumerate(evidence_dicts):
        spans = evidence.get("spans") or []
        evidence_type = evidence.get("type", "unknown")
        for s_idx, span in enumerate(spans):
            text = span.get("text", "")
            if not text:
                continue

            units.append(
                EvidenceUnit(
                    evidence_id=f"{document_id}:{e_idx}:{s_idx}",
                    document_id=document_id,
                    content=text,
                    page_number=span.get("page"),
                    source_type=evidence_type,
                    metadata={
                        "start": span.get("start"),
                        "end": span.get("end"),
                        "problem_text": record.get("problem_text"),
                    },
                )
            )

    return units


def build_evidence_units_from_ocr(
    document_id: str,
    filename: str,
    md_results: str,
    layout_details: list,
) -> list[EvidenceUnit]:
    """Build evidence units from OCR response layout details."""

    units: list[EvidenceUnit] = []
    seen_contents: set[str] = set()
    for page_idx, page in enumerate(layout_details, start=1):
        for elem_idx, element in enumerate(page):
            if hasattr(element, "model_dump"):
                data = element.model_dump()
            elif isinstance(element, dict):
                data = element
            else:
                continue

            content = str(data.get("content", "")).strip()
            if not content:
                continue
            normalized_content = re.sub(r"\s+", " ", content).strip().lower()
            if not normalized_content:
                continue
            seen_contents.add(normalized_content)

            units.append(
                EvidenceUnit(
                    evidence_id=f"{document_id}:p{page_idx}:e{elem_idx}",
                    document_id=document_id,
                    content=content,
                    source_type=str(data.get("label", "layout")),
                    page_number=page_idx,
                    metadata={
                        "filename": filename,
                        "layout_index": data.get("index"),
                    },
                )
            )

    if units:
        markdown_blocks = [block.strip() for block in re.split(r"\n\s*\n", md_results or "") if block.strip()]
        for block_idx, block in enumerate(markdown_blocks):
            normalized_block = re.sub(r"\s+", " ", block).strip().lower()
            if not normalized_block or normalized_block in seen_contents:
                continue
            if block.lstrip().startswith("#") and "\n" not in block:
                # Skip standalone markdown headings when layout already contains the real content.
                continue
            units.append(
                EvidenceUnit(
                    evidence_id=f"{document_id}:markdown:{block_idx}",
                    document_id=document_id,
                    content=block,
                    source_type="markdown_block",
                    page_number=1,
                    metadata={"filename": filename, "markdown_block_index": block_idx},
                )
            )
    elif md_results.strip():
        units.append(
            EvidenceUnit(
                evidence_id=f"{document_id}:markdown:0",
                document_id=document_id,
                content=md_results.strip(),
                source_type="markdown",
                page_number=1,
                metadata={"filename": filename},
            )
        )

    return units
