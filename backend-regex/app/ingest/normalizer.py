"""Normalization helpers for extracted document content."""

import re
from decimal import Decimal

from pydantic import BaseModel, Field


DATE_PATTERN = re.compile(r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b")
AMOUNT_PATTERN = re.compile(
    r"(?:(?:USD|EUR|MAD|€|\$)\s*)?([0-9]{1,3}(?:[ ,._][0-9]{3})*(?:[.,][0-9]{2})?|[0-9]+(?:[.,][0-9]{2})?)\s*(?:USD|EUR|MAD|€|\$)?",
    re.IGNORECASE,
)
REFERENCE_PATTERN = re.compile(r"\b(?:REF|DOC|REV|ID)[-_:/]?[A-Z0-9-]{2,}\b", re.IGNORECASE)


class NormalizedFields(BaseModel):
    """Normalized fields extracted from text."""

    dates: list[str] = Field(default_factory=list)
    amounts: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)


def _normalize_amount_token(value: str) -> str:
    clean = value.replace(" ", "").replace("_", "")
    if "," in clean and "." in clean:
        if clean.rfind(",") > clean.rfind("."):
            clean = clean.replace(".", "").replace(",", ".")
        else:
            clean = clean.replace(",", "")
    elif "," in clean:
        clean = clean.replace(",", ".")
    return str(Decimal(clean))


def normalize_text_fields(text: str) -> NormalizedFields:
    """Extract and normalize dates, amounts and references."""

    dates = sorted({m.group(1) for m in DATE_PATTERN.finditer(text)})

    raw_amounts = []
    for match in AMOUNT_PATTERN.finditer(text):
        token = match.group(1)
        if not token:
            continue
        try:
            normalized = _normalize_amount_token(token)
        except Exception:
            continue
        raw_amounts.append(normalized)
    amounts = sorted(set(raw_amounts))

    references = sorted({m.group(0).upper() for m in REFERENCE_PATTERN.finditer(text)})

    return NormalizedFields(dates=dates, amounts=amounts, references=references)


def normalize_metadata(metadata: dict) -> dict:
    """Normalize metadata keys and strip empty values."""

    normalized: dict = {}
    for key, value in metadata.items():
        normalized_key = str(key).strip().lower().replace(" ", "_")
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue
        normalized[normalized_key] = value
    return normalized

