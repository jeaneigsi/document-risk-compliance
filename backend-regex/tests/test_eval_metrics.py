"""Tests for Phase 7 evaluation metrics."""

import pytest

from app.eval.metrics import (
    compression_ratio,
    estimate_cost,
    precision_recall_f1,
    summarize_economic_metrics,
    token_count,
)


def test_precision_recall_f1():
    scores = precision_recall_f1(
        gold_labels=[True, True, False, False],
        predicted_labels=[True, False, True, False],
    )
    assert scores["precision"] == 0.5
    assert scores["recall"] == 0.5
    assert scores["f1"] == 0.5
    assert scores["tp"] == 1.0
    assert scores["fp"] == 1.0
    assert scores["fn"] == 1.0


def test_precision_recall_f1_length_mismatch():
    with pytest.raises(ValueError):
        precision_recall_f1([True], [True, False])


def test_token_count_and_compression_ratio():
    assert token_count("a b   c") == 3
    assert compression_ratio(100, 35) == 0.35
    assert compression_ratio(0, 10) == 1.0


def test_estimate_cost():
    cost = estimate_cost(
        usage={"prompt_tokens": 1500, "completion_tokens": 500},
        input_price_per_1k=0.001,
        output_price_per_1k=0.002,
    )
    assert cost == pytest.approx(0.0025)


def test_summarize_economic_metrics():
    summary = summarize_economic_metrics(
        [
            {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "cost_usd": 0.01,
                "latency_ms": 300,
                "compression_ratio": 0.4,
                "llm_calls": 1,
            },
            {
                "prompt_tokens": 200,
                "completion_tokens": 40,
                "cost_usd": 0.02,
                "latency_ms": 500,
                "compression_ratio": 0.5,
                "llm_calls": 2,
            },
        ]
    )
    assert summary["runs"] == 2.0
    assert summary["total_tokens"] == 360.0
    assert summary["total_cost_usd"] == pytest.approx(0.03)
    assert summary["avg_latency_ms"] == 400.0
    assert summary["avg_compression_ratio"] == pytest.approx(0.45)
    assert summary["total_llm_calls"] == 3.0
