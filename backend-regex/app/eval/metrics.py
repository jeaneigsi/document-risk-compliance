"""Evaluation metrics for Phase 7."""

import math
import re


def recall_at_k(relevant_ids: set[str], retrieved_ids: list[str], k: int) -> float:
    if not relevant_ids:
        return 0.0
    top = retrieved_ids[:k]
    hits = len(relevant_ids & set(top))
    return hits / len(relevant_ids)


def mrr(relevant_ids: set[str], retrieved_ids: list[str]) -> float:
    for rank, doc_id in enumerate(retrieved_ids, start=1):
        if doc_id in relevant_ids:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(relevance_by_id: dict[str, float], retrieved_ids: list[str], k: int) -> float:
    top = retrieved_ids[:k]
    dcg = 0.0
    for i, doc_id in enumerate(top, start=1):
        rel = float(relevance_by_id.get(doc_id, 0.0))
        if rel > 0:
            dcg += rel / math.log2(i + 1)

    ideal_rels = sorted((float(v) for v in relevance_by_id.values() if v > 0), reverse=True)[:k]
    idcg = 0.0
    for i, rel in enumerate(ideal_rels, start=1):
        idcg += rel / math.log2(i + 1)

    if idcg == 0:
        return 0.0
    return max(0.0, min(1.0, dcg / idcg))


def precision_recall_f1(gold_labels: list[bool], predicted_labels: list[bool]) -> dict[str, float]:
    if len(gold_labels) != len(predicted_labels):
        raise ValueError("gold_labels and predicted_labels must have same length")

    tp = sum(1 for g, p in zip(gold_labels, predicted_labels) if g and p)
    fp = sum(1 for g, p in zip(gold_labels, predicted_labels) if not g and p)
    fn = sum(1 for g, p in zip(gold_labels, predicted_labels) if g and not p)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": float(tp),
        "fp": float(fp),
        "fn": float(fn),
    }


def compression_ratio(original_size: int, compressed_size: int) -> float:
    if original_size <= 0:
        return 1.0
    safe_compressed = max(0, compressed_size)
    return safe_compressed / original_size


def token_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def estimate_cost(
    usage: dict,
    input_price_per_1k: float,
    output_price_per_1k: float,
) -> float:
    prompt_tokens = int(usage.get("prompt_tokens", 0))
    completion_tokens = int(usage.get("completion_tokens", 0))
    return (prompt_tokens / 1000.0) * input_price_per_1k + (completion_tokens / 1000.0) * output_price_per_1k


def summarize_economic_metrics(samples: list[dict]) -> dict[str, float]:
    if not samples:
        return {
            "runs": 0.0,
            "total_prompt_tokens": 0.0,
            "total_completion_tokens": 0.0,
            "total_tokens": 0.0,
            "total_cost_usd": 0.0,
            "avg_latency_ms": 0.0,
            "avg_compression_ratio": 1.0,
            "total_llm_calls": 0.0,
        }

    total_prompt = float(sum(int(s.get("prompt_tokens", 0)) for s in samples))
    total_completion = float(sum(int(s.get("completion_tokens", 0)) for s in samples))
    total_cost = float(sum(float(s.get("cost_usd", 0.0)) for s in samples))
    total_latency = float(sum(float(s.get("latency_ms", 0.0)) for s in samples))
    total_compression = float(sum(float(s.get("compression_ratio", 1.0)) for s in samples))
    total_llm_calls = float(sum(int(s.get("llm_calls", 0)) for s in samples))

    runs = float(len(samples))
    return {
        "runs": runs,
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "total_tokens": total_prompt + total_completion,
        "total_cost_usd": total_cost,
        "avg_latency_ms": total_latency / runs,
        "avg_compression_ratio": total_compression / runs,
        "total_llm_calls": total_llm_calls,
    }
