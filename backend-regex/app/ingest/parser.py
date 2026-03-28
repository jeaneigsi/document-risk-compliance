"""Document parsers for Phase 2 ingestion."""

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ParsedPage(BaseModel):
    """Parsed content for one page."""

    page_number: int = Field(..., ge=1)
    text: str = ""
    tables: list[dict[str, Any]] = Field(default_factory=list)


class ParsedDocument(BaseModel):
    """Canonical parsed document."""

    file_path: str
    filename: str
    total_pages: int = Field(..., ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    pages: list[ParsedPage] = Field(default_factory=list)


def _load_fitz():
    try:
        import fitz  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised via tests with monkeypatch
        raise RuntimeError("PyMuPDF (fitz) is required for PDF parsing") from exc
    return fitz


def _load_camelot():
    try:
        import camelot  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised via tests with monkeypatch
        raise RuntimeError("camelot-py is required for table extraction") from exc
    return camelot


def parse_pdf(file_path: str | Path, extract_tables: bool = False) -> ParsedDocument:
    """Parse PDF text (and optionally tables) into a canonical structure."""

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF file not found: {path}")

    fitz = _load_fitz()
    document = fitz.open(path)

    pages: list[ParsedPage] = []
    for i in range(len(document)):
        page = document[i]
        pages.append(
            ParsedPage(
                page_number=i + 1,
                text=page.get_text("text") or "",
                tables=[],
            )
        )

    parsed = ParsedDocument(
        file_path=str(path),
        filename=path.name,
        total_pages=len(document),
        metadata=dict(getattr(document, "metadata", {}) or {}),
        pages=pages,
    )

    if extract_tables:
        camelot = _load_camelot()
        try:
            tables = camelot.read_pdf(str(path), pages="all")
        except Exception:
            tables = []

        for table in tables:
            page_num = int(getattr(table, "page", 1))
            if 1 <= page_num <= len(parsed.pages):
                parsed.pages[page_num - 1].tables.append(
                    {
                        "page": page_num,
                        "shape": getattr(getattr(table, "df", None), "shape", None),
                    }
                )

    return parsed

