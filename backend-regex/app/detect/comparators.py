"""Specialized comparators for textual/table/section consistency."""

from difflib import SequenceMatcher


NEGATION_MARKERS = {"not", "no", "never", "none", "without", "aucun", "pas"}


def _tokenize(text: str) -> list[str]:
    return [token.strip(".,;:!?()[]{}\"'").lower() for token in text.split() if token.strip()]


class ClauseComparator:
    """Compare two clauses and highlight probable contradictions."""

    def compare(self, claim_text: str, evidence_text: str) -> dict:
        ratio = SequenceMatcher(a=claim_text.lower(), b=evidence_text.lower()).ratio()
        claim_tokens = set(_tokenize(claim_text))
        evidence_tokens = set(_tokenize(evidence_text))
        negation_mismatch = bool((claim_tokens & NEGATION_MARKERS) ^ (evidence_tokens & NEGATION_MARKERS))
        conflict = ratio > 0.35 and negation_mismatch
        return {
            "similarity": round(ratio, 4),
            "negation_mismatch": negation_mismatch,
            "conflict": conflict,
            "type": "clause_conflict" if conflict else "clause_consistent",
        }


class TableComparator:
    """Compare numeric signatures between two table-like payloads."""

    def compare(self, claim_numbers: list[str], evidence_numbers: list[str]) -> dict:
        claim_set = set(claim_numbers)
        evidence_set = set(evidence_numbers)
        overlap = claim_set & evidence_set
        return {
            "claim_count": len(claim_set),
            "evidence_count": len(evidence_set),
            "overlap_count": len(overlap),
            "conflict": bool(claim_set and evidence_set and not overlap),
            "type": "table_conflict" if claim_set and evidence_set and not overlap else "table_consistent",
        }


class SectionComparator:
    """Compare larger sections using normalized edit similarity."""

    def compare(self, section_a: str, section_b: str) -> dict:
        ratio = SequenceMatcher(a=section_a.lower(), b=section_b.lower()).ratio()
        return {
            "similarity": round(ratio, 4),
            "changed": ratio < 0.75,
            "type": "section_changed" if ratio < 0.75 else "section_stable",
        }

