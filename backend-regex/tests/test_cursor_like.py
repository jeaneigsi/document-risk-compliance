"""Tests for cursor-like lexical indexing."""

from app.search.cursor_like import CursorLikeIndex


def test_cursor_like_index_search_returns_ranked_hits():
    index = CursorLikeIndex()
    index.add_documents(
        [
            {"id": "d1", "text": "budget annuel 50 millions", "metadata": {}},
            {"id": "d2", "text": "date de livraison 2026-03-25", "metadata": {}},
            {"id": "d3", "text": "budget trimestriel 10 millions", "metadata": {}},
        ]
    )

    results = index.search("budget millions", top_k=2)
    assert len(results) == 2
    assert results[0]["id"] in {"d1", "d3"}
    assert results[0]["score"] >= results[1]["score"]


def test_cursor_like_regex_search_filters_false_positives():
    index = CursorLikeIndex()
    index.add_documents(
        [
            {"id": "d1", "text": "error: budget code is 900", "metadata": {}},
            {"id": "d2", "text": "error and budget mentioned but no number", "metadata": {}},
            {"id": "d3", "text": "budget only", "metadata": {}},
        ]
    )

    results = index.search(r"error.*budget.*\d+", top_k=10)
    assert [item["id"] for item in results] == ["d1"]


def test_cursor_like_regex_slash_flags_are_supported():
    index = CursorLikeIndex()
    index.add_documents(
        [
            {"id": "d1", "text": "Budget annuel", "metadata": {}},
            {"id": "d2", "text": "nothing relevant", "metadata": {}},
        ]
    )

    results = index.search("/budget/i", top_k=10)
    assert [item["id"] for item in results] == ["d1"]


def test_cursor_like_invalid_regex_falls_back_to_plain_search():
    index = CursorLikeIndex()
    index.add_documents(
        [
            {"id": "d1", "text": "budget trimestriel", "metadata": {}},
            {"id": "d2", "text": "deadline", "metadata": {}},
        ]
    )

    results = index.search(r"budget(", top_k=10)
    assert results
    assert results[0]["id"] == "d1"


def test_cursor_like_rg_strategy_full_scan():
    index = CursorLikeIndex()
    index.add_documents(
        [
            {"id": "d1", "text": "Error code 500 on budget service", "metadata": {}},
            {"id": "d2", "text": "Budget update applied", "metadata": {}},
        ]
    )

    results = index.rg_search(r"Error.*500", top_k=10)
    assert [item["id"] for item in results] == ["d1"]
