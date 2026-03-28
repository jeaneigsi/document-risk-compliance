"""Tests for regex query planning."""

from app.search.regex_planner import build_regex_query_plan


def test_regex_planner_marks_plain_query_as_non_regex():
    plan = build_regex_query_plan("budget deadline")
    assert plan is not None
    assert plan.is_regex is False
    assert plan.clauses == []


def test_regex_planner_builds_alternation_clauses():
    plan = build_regex_query_plan(r"(budget|deadline)\s+2026")
    assert plan is not None
    assert plan.is_regex is True
    assert len(plan.clauses) >= 2
    union = set().union(*plan.clauses)
    assert any(t in union for t in {"bud", "udg", "dge"})
    assert any(t in union for t in {"dea", "ead", "adl"})


def test_regex_planner_invalid_regex_returns_none():
    plan = build_regex_query_plan(r"budget(")
    assert plan is None
