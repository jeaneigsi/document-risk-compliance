"""Ranking utilities for hybrid search."""

from typing import Any


def rank_search_results(
    semantic_results: list[dict[str, Any]],
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """Sort semantic results by score descending and keep top_k."""
    sorted_results = sorted(
        semantic_results,
        key=lambda item: float(item.get("score", 0.0)),
        reverse=True,
    )
    return sorted_results[:top_k]


def _ensure_id(item: dict[str, Any]) -> str:
    for key in ("id", "evidence_id", "document_id"):
        value = item.get(key)
        if value:
            return str(value)
    return ""


def fuse_search_results(
    semantic_results: list[dict[str, Any]],
    lexical_results: list[dict[str, Any]],
    top_k: int = 10,
    semantic_weight: float = 0.55,
    lexical_weight: float = 0.45,
) -> list[dict[str, Any]]:
    """Fuse semantic and lexical results using calibrated score + rank signals."""

    by_id: dict[str, dict[str, Any]] = {}
    rank_denominator = max(60, top_k * 6)

    def normalize_scores(items: list[dict[str, Any]]) -> dict[str, float]:
        scores_by_id = {
            _ensure_id(item): float(item.get("score", 0.0))
            for item in items
            if _ensure_id(item)
        }
        if not scores_by_id:
            return {}
        score_values = list(scores_by_id.values())
        min_score = min(score_values)
        max_score = max(score_values)
        if max_score <= min_score:
            return {item_id: 1.0 for item_id in scores_by_id}
        return {
            item_id: (score - min_score) / (max_score - min_score)
            for item_id, score in scores_by_id.items()
        }

    semantic_norm = normalize_scores(semantic_results)
    lexical_norm = normalize_scores(lexical_results)

    def merge(items: list[dict[str, Any]], source: str, weight: float, norm_scores: dict[str, float]) -> None:
        for rank, item in enumerate(items, start=1):
            item_id = _ensure_id(item)
            if not item_id:
                continue
            score = float(item.get("score", 0.0))
            score_norm = float(norm_scores.get(item_id, 0.0))
            rank_component = 1.0 / (rank_denominator + rank)
            entry = by_id.setdefault(
                item_id,
                {
                    "id": item_id,
                    "score": 0.0,
                    "semantic_score": 0.0,
                    "lexical_score": 0.0,
                    "semantic_rank": None,
                    "lexical_rank": None,
                    "sources": set(),
                    "metadata": item.get("metadata", {}),
                    "text": item.get("text"),
                },
            )
            fused_component = (0.65 * score_norm) + (0.35 * rank_component)
            entry["score"] += fused_component * weight
            entry[f"{source}_score"] = max(entry[f"{source}_score"], score)
            entry[f"{source}_rank"] = rank
            entry["sources"].add(source)
            if not entry.get("text"):
                entry["text"] = item.get("text")
            if not entry.get("metadata"):
                entry["metadata"] = item.get("metadata", {})

    merge(semantic_results, "semantic", semantic_weight, semantic_norm)
    merge(lexical_results, "lexical", lexical_weight, lexical_norm)

    fused = []
    for entry in by_id.values():
        entry["sources"] = sorted(entry["sources"])
        if len(entry["sources"]) == 2:
            entry["score"] += 0.08
        elif "lexical" in entry["sources"] and (entry.get("lexical_rank") or 999) <= max(3, top_k // 2):
            entry["score"] += 0.03
        entry["score"] = round(float(entry["score"]), 6)
        fused.append(entry)

    fused.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
    return fused[:top_k]
