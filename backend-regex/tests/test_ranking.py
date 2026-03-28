"""Tests for ranking utilities."""

from app.search.ranking import fuse_search_results, rank_search_results


def test_rank_search_results_orders_by_score():
    results = [
        {"id": "a", "score": 0.2},
        {"id": "b", "score": 0.9},
        {"id": "c", "score": 0.5},
    ]
    ranked = rank_search_results(results, top_k=2)
    assert [item["id"] for item in ranked] == ["b", "c"]


def test_fuse_search_results_combines_sources():
    semantic = [{"id": "a", "score": 0.9}, {"id": "b", "score": 0.2}]
    lexical = [{"id": "a", "score": 0.3}, {"id": "c", "score": 0.8}]
    fused = fuse_search_results(semantic, lexical, top_k=3)
    assert fused[0]["id"] == "a"
    assert "semantic" in fused[0]["sources"]
    assert "lexical" in fused[0]["sources"]
