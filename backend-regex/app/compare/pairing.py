"""Pair candidate evidence rows for structured document comparison."""

from __future__ import annotations

import difflib
from typing import Any

from app.compare.normalization import (
    category_keywords,
    extract_facts,
    extract_section_hint,
    normalize_text,
    select_facts_for_category,
)


def pair_evidence_rows(
    claim: str,
    category: str,
    left_rows: list[dict[str, Any]],
    right_rows: list[dict[str, Any]],
    max_pairs: int = 3,
    candidate_limit: int | None = None,
) -> list[dict[str, Any]]:
    limit = candidate_limit if candidate_limit is not None else max(4, max_pairs)
    enriched_left = [_enrich_row(row, category) for row in left_rows[:limit]]
    enriched_right = [_enrich_row(row, category) for row in right_rows[:limit]]
    pairs: list[dict[str, Any]] = []

    for left in enriched_left:
        for right in enriched_right:
            pair_score, reason = _score_pair(left, right, claim, category)
            pairs.append(
                {
                    "pair_score": round(pair_score, 6),
                    "pairing_reason": reason,
                    "shared_field_types": sorted({
                        fact["field_type"]
                        for fact in left["facts"]
                        for other in right["facts"]
                        if fact["field_type"] == other["field_type"]
                    }),
                    "left": left,
                    "right": right,
                }
            )

    pairs.sort(key=lambda item: item["pair_score"], reverse=True)
    return pairs[:max_pairs]


def _enrich_row(row: dict[str, Any], category: str) -> dict[str, Any]:
    facts = [fact.to_dict() for fact in select_facts_for_category(extract_facts(row.get("text", ""), category), category)]
    return {
        "row": row,
        "facts": facts,
        "section_hint": extract_section_hint(row.get("text", "")),
        "normalized_text": normalize_text(row.get("text", "")),
        "base_score": float(row.get("score", 0.0)),
    }


def _score_pair(left: dict[str, Any], right: dict[str, Any], claim: str, category: str) -> tuple[float, str]:
    score = left["base_score"] + right["base_score"]
    reasons: list[str] = []

    left_types = {fact["field_type"] for fact in left["facts"]}
    right_types = {fact["field_type"] for fact in right["facts"]}
    shared_types = left_types & right_types
    if shared_types:
        score += 2.0 + (0.25 * len(shared_types))
        reasons.append(f"shared_fields={','.join(sorted(shared_types))}")

    if left.get("section_hint") and right.get("section_hint"):
        if normalize_text(left["section_hint"]) == normalize_text(right["section_hint"]):
            score += 1.25
            reasons.append("same_section_hint")

    if category != "general":
        keywords = category_keywords(category)
        left_text = left["normalized_text"]
        right_text = right["normalized_text"]
        if any(keyword in left_text for keyword in keywords):
            score += 0.8
            reasons.append("left_category_match")
        if any(keyword in right_text for keyword in keywords):
            score += 0.8
            reasons.append("right_category_match")

    claim_terms = {token for token in normalize_text(claim).split(" ") if len(token) > 3}
    if claim_terms:
        left_overlap = sum(1 for term in claim_terms if term in left["normalized_text"])
        right_overlap = sum(1 for term in claim_terms if term in right["normalized_text"])
        overlap = left_overlap + right_overlap
        if overlap:
            score += overlap * 0.12
            reasons.append(f"claim_overlap={overlap}")

    if left["normalized_text"] == right["normalized_text"] and left["normalized_text"]:
        score += 0.5
        reasons.append("exact_text_match")
    elif left["normalized_text"] and right["normalized_text"]:
        similarity = difflib.SequenceMatcher(
            a=left["normalized_text"],
            b=right["normalized_text"],
            autojunk=False,
        ).ratio()
        if similarity >= 0.55:
            score += similarity * 1.5
            reasons.append(f"text_similarity={similarity:.2f}")

    return score, ", ".join(reasons) if reasons else "ranked_by_retrieval_score"
