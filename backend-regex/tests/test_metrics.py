"""Tests for search metrics."""

from app.search.metrics import mrr, ndcg_at_k, recall_at_k


def test_recall_at_k():
    assert recall_at_k({"a", "c"}, ["a", "b", "c"], k=2) == 0.5


def test_mrr():
    assert mrr({"x"}, ["a", "x", "b"]) == 0.5
    assert mrr({"z"}, ["a", "x", "b"]) == 0.0


def test_ndcg_at_k():
    relevance = {"a": 3.0, "b": 2.0, "c": 1.0}
    score = ndcg_at_k(relevance, ["b", "a", "x"], k=3)
    assert 0.0 <= score <= 1.0

