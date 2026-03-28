"""Lightweight field normalization for text-first document comparison."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Iterable


KEYWORD_GROUPS: dict[str, tuple[str, ...]] = {
    "liability": ("liability", "responsabil", "cap", "limitation of liability", "plafond"),
    "termination": ("termination", "terminate", "resiliation", "résiliation", "notice", "préavis", "preavis"),
    "effective_date": ("effective date", "date d'effet", "entry into force", "date de prise d'effet"),
    "payment": ("payment", "paiement", "invoice", "facture", "due", "échéance", "echeance"),
    "governing_law": ("governing law", "droit applicable", "jurisdiction", "tribunal", "court"),
    "confidentiality": ("confidentiality", "confidential", "confidentiel", "nda"),
    "reference": ("reference", "ref", "référence", "revision", "version"),
    "general": tuple(),
}

AMOUNT_RE = re.compile(r"\b\d[\d\s.,]*(?:€|eur|usd|\$|mad)\b", re.IGNORECASE)
DATE_RE = re.compile(
    r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{2}[/-]\d{2}|"
    r"\d{1,2}\s+(?:janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|octobre|novembre|décembre|decembre|"
    r"january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{4})\b",
    re.IGNORECASE,
)
DURATION_RE = re.compile(
    r"\b\d{1,3}\s+(?:day|days|jour|jours|month|months|mois|year|years|an|ans)\b",
    re.IGNORECASE,
)
REFERENCE_RE = re.compile(
    r"\b(?:ref(?:erence)?|référence|version|revision)\s*[:#-]?\s*[A-Z0-9][A-Z0-9._/-]*\b",
    re.IGNORECASE,
)
CLAUSE_RE = re.compile(r"\b(?:shall|must|will|may not|cannot|doit|devra|ne peut pas)\b", re.IGNORECASE)


@dataclass
class NormalizedFact:
    field_type: str
    raw_value: str
    normalized_value: str
    category: str
    confidence: float = 1.0

    def to_dict(self) -> dict:
        return asdict(self)


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def detect_claim_category(claim: str) -> str:
    normalized = normalize_text(claim)
    for category, keywords in KEYWORD_GROUPS.items():
        if any(keyword in normalized for keyword in keywords):
            return category
    if AMOUNT_RE.search(normalized):
        return "payment"
    if DATE_RE.search(normalized):
        return "effective_date"
    return "general"


def category_keywords(category: str) -> tuple[str, ...]:
    return KEYWORD_GROUPS.get(category, tuple())


def extract_facts(text: str, preferred_category: str | None = None) -> list[NormalizedFact]:
    content = text or ""
    normalized_content = normalize_text(content)
    facts: list[NormalizedFact] = []
    seen: set[tuple[str, str, str]] = set()

    def add_unique(field_type: str, raw_value: str, normalized_value: str, category: str, confidence: float = 1.0) -> None:
        if not raw_value or not normalized_value:
            return
        if preferred_category and preferred_category != "general" and category != preferred_category:
            if field_type not in {"amount", "date", "duration"}:
                return
        candidate = (field_type, normalized_value, category)
        if candidate in seen:
            return
        seen.add(candidate)
        facts.append(
            NormalizedFact(
                field_type=field_type,
                raw_value=raw_value.strip(),
                normalized_value=normalized_value,
                category=category,
                confidence=confidence,
            )
        )

    for match in AMOUNT_RE.finditer(content):
        raw = match.group(0).strip()
        normalized = re.sub(r"\s+", "", raw.lower()).replace(",", ".")
        category = "payment" if any(token in normalized_content for token in category_keywords("payment")) else "liability"
        add_unique("amount", raw, normalized, category)

    for match in DATE_RE.finditer(content):
        raw = match.group(0).strip()
        add_unique("date", raw, normalize_text(raw), "effective_date")

    for match in DURATION_RE.finditer(content):
        raw = match.group(0).strip()
        category = "termination" if any(token in normalized_content for token in category_keywords("termination")) else "general"
        add_unique("duration", raw, normalize_text(raw), category, confidence=0.9)

    for match in REFERENCE_RE.finditer(content):
        raw = match.group(0).strip()
        add_unique("reference", raw, normalize_text(raw), "reference", confidence=0.8)

    if any(keyword in normalized_content for keyword in category_keywords("governing_law")):
        snippet = _extract_sentence(content, category_keywords("governing_law"))
        add_unique("jurisdiction", snippet, normalize_text(snippet), "governing_law", confidence=0.75)

    if any(keyword in normalized_content for keyword in category_keywords("confidentiality")):
        snippet = _extract_sentence(content, category_keywords("confidentiality"))
        add_unique("confidentiality", snippet, normalize_text(snippet), "confidentiality", confidence=0.7)

    if any(keyword in normalized_content for keyword in category_keywords("termination")) and not any(f.category == "termination" for f in facts):
        snippet = _extract_sentence(content, category_keywords("termination"))
        add_unique("termination_clause", snippet, normalize_text(snippet), "termination", confidence=0.65)

    if any(keyword in normalized_content for keyword in category_keywords("liability")) and not any(f.category == "liability" for f in facts):
        snippet = _extract_sentence(content, category_keywords("liability"))
        add_unique("liability_clause", snippet, normalize_text(snippet), "liability", confidence=0.65)

    if CLAUSE_RE.search(content) and not facts:
        snippet = _extract_sentence(content, ())
        add_unique("clause_text", snippet, normalize_text(snippet), preferred_category or "general", confidence=0.5)

    return facts


def select_facts_for_category(facts: Iterable[NormalizedFact], category: str) -> list[NormalizedFact]:
    rows = list(facts)
    if category == "general":
        return rows
    matched = [fact for fact in rows if fact.category == category]
    return matched or rows


def extract_section_hint(text: str) -> str | None:
    chunks = [chunk.strip() for chunk in re.split(r"\n+", text or "") if chunk.strip()]
    if not chunks:
        return None
    first = chunks[0].strip(" :.-")
    normalized = normalize_text(first)
    if not normalized:
        return None
    if len(first) <= 90 and (
        first.startswith("#")
        or first.isupper()
        or re.match(r"^(section|article|clause)\b", normalized)
        or normalized in KEYWORD_GROUPS
    ):
        return first.lstrip("# ").strip()
    if len(first) <= 60 and ":" not in first and len(chunks) > 1:
        return first
    return None


def _extract_sentence(text: str, keywords: tuple[str, ...]) -> str:
    chunks = [chunk.strip() for chunk in re.split(r"(?<=[.;:])\s+|\n+", text or "") if chunk.strip()]
    if not chunks:
        return (text or "").strip()[:240]
    if not keywords:
        return chunks[0][:240]
    for chunk in chunks:
        normalized = normalize_text(chunk)
        if any(keyword in normalized for keyword in keywords):
            return chunk[:240]
    return chunks[0][:240]
