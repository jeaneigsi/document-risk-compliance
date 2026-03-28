"""Deterministic inconsistency detectors."""

import re
from decimal import Decimal


DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b")
AMOUNT_RE = re.compile(
    r"(?:(?:USD|EUR|MAD|€|\$)\s*)?([0-9]{1,3}(?:[ ,._][0-9]{3})*(?:[.,][0-9]{2})?|[0-9]+(?:[.,][0-9]{2})?)\s*(?:USD|EUR|MAD|€|\$)?",
    re.IGNORECASE,
)
REF_RE = re.compile(r"\b(?:REF|DOC|REV|ID)[-_:/]?[A-Z0-9-]{2,}\b", re.IGNORECASE)


def _normalize_amount(value: str) -> str:
    clean = value.replace(" ", "").replace("_", "")
    if "," in clean and "." in clean:
        if clean.rfind(",") > clean.rfind("."):
            clean = clean.replace(".", "").replace(",", ".")
        else:
            clean = clean.replace(",", "")
    elif "," in clean:
        clean = clean.replace(",", ".")
    return str(Decimal(clean))


class DateConflictDetector:
    """Detect conflicts based on divergent dates."""

    def detect(self, claim_text: str, evidence_text: str) -> list[dict]:
        claim_dates = {m.group(1) for m in DATE_RE.finditer(claim_text)}
        evidence_dates = {m.group(1) for m in DATE_RE.finditer(evidence_text)}
        if not claim_dates or not evidence_dates:
            return []
        if claim_dates & evidence_dates:
            return []
        return [
            {
                "type": "date_conflict",
                "severity_hint": "high",
                "claim_values": sorted(claim_dates),
                "evidence_values": sorted(evidence_dates),
            }
        ]


class AmountConflictDetector:
    """Detect conflicts based on divergent amounts."""

    def detect(self, claim_text: str, evidence_text: str) -> list[dict]:
        claim_amounts = {_normalize_amount(m.group(1)) for m in AMOUNT_RE.finditer(claim_text)}
        evidence_amounts = {_normalize_amount(m.group(1)) for m in AMOUNT_RE.finditer(evidence_text)}
        if not claim_amounts or not evidence_amounts:
            return []
        if claim_amounts & evidence_amounts:
            return []
        return [
            {
                "type": "amount_conflict",
                "severity_hint": "critical",
                "claim_values": sorted(claim_amounts),
                "evidence_values": sorted(evidence_amounts),
            }
        ]


class ReferenceMismatchDetector:
    """Detect conflicts on structured references."""

    def detect(self, claim_text: str, evidence_text: str) -> list[dict]:
        claim_refs = {m.group(0).upper() for m in REF_RE.finditer(claim_text)}
        evidence_refs = {m.group(0).upper() for m in REF_RE.finditer(evidence_text)}
        if not claim_refs or not evidence_refs:
            return []
        if claim_refs & evidence_refs:
            return []
        return [
            {
                "type": "reference_mismatch",
                "severity_hint": "medium",
                "claim_values": sorted(claim_refs),
                "evidence_values": sorted(evidence_refs),
            }
        ]

