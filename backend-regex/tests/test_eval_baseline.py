"""Tests for baseline retrieval."""

from app.eval.baseline import BaselineLexicalRetriever


def test_baseline_search_ranks_overlap_first():
    retriever = BaselineLexicalRetriever()
    corpus = [
        {"id": "a", "text": "delivery deadline is 2026-01-10"},
        {"id": "b", "text": "budget approved amount is 1000 eur"},
        {"id": "c", "text": "deadline extension approved for delivery"},
    ]
    results = retriever.search(query="delivery deadline", corpus=corpus, top_k=3)

    assert len(results) >= 2
    assert results[0]["id"] in {"a", "c"}
    assert all(item["source"] == "baseline" for item in results)


def test_baseline_empty_query():
    retriever = BaselineLexicalRetriever()
    results = retriever.search(query="   ", corpus=[{"id": "a", "text": "x"}], top_k=5)
    assert results == []
