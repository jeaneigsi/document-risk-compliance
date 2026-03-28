"""Backward-compatible exports for search metrics."""

from app.eval.metrics import mrr, ndcg_at_k, recall_at_k

__all__ = ["recall_at_k", "mrr", "ndcg_at_k"]
