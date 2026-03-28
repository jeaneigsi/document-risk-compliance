"""Evaluation framework (Phase 7)."""

from app.eval.baseline import BaselineLexicalRetriever
from app.eval.datasets import (
    build_find_eval_pack_from_rows,
    export_rows_to_jsonl,
    load_find_eval_pack,
    load_rows_from_jsonl,
    load_streaming_dataset,
    materialize_dataset,
    stream_take,
)
from app.eval.metrics import (
    compression_ratio,
    estimate_cost,
    mrr,
    ndcg_at_k,
    precision_recall_f1,
    recall_at_k,
    summarize_economic_metrics,
    token_count,
)
from app.eval.models import DetectionEvalSample, EconomicSample, SearchEvalSample
from app.eval.runner import EvaluationRunner

__all__ = [
    "BaselineLexicalRetriever",
    "EvaluationRunner",
    "load_streaming_dataset",
    "materialize_dataset",
    "stream_take",
    "export_rows_to_jsonl",
    "load_rows_from_jsonl",
    "load_find_eval_pack",
    "build_find_eval_pack_from_rows",
    "SearchEvalSample",
    "DetectionEvalSample",
    "EconomicSample",
    "recall_at_k",
    "mrr",
    "ndcg_at_k",
    "precision_recall_f1",
    "compression_ratio",
    "token_count",
    "estimate_cost",
    "summarize_economic_metrics",
]
