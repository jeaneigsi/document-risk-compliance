"""Tests for evaluation runner."""

import pytest

from app.eval.models import SearchEvalSample
from app.eval.runner import EvaluationRunner


class _FakeSearchPipeline:
    def __init__(self):
        self.index_calls = []

    async def run(self, query: str, index_name: str, top_k: int, strategy: str):
        assert strategy in {"semantic", "lexical", "hybrid"}
        return {
            "status": "completed",
            "results": [
                {"id": "doc-1", "score": 0.9},
                {"id": "doc-2", "score": 0.5},
            ],
            "latency_ms": 12.0,
            "candidate_count": 5,
            "candidate_kept_count": 2,
        }

    async def index_evidence_units(self, evidence_units, index_name: str):
        self.index_calls.append((index_name, len(evidence_units)))
        return {"status": "completed", "indexed_count": len(evidence_units), "index_name": index_name}


class _FailingSearchPipeline(_FakeSearchPipeline):
    async def run(self, query: str, index_name: str, top_k: int, strategy: str):
        raise RuntimeError("remote disconnect")


@pytest.mark.asyncio
async def test_evaluate_search_baseline():
    runner = EvaluationRunner()
    samples = [
        SearchEvalSample(
            sample_id="s1",
            query="delivery deadline",
            relevant_ids={"doc-1"},
            relevance_by_id={"doc-1": 2.0},
        )
    ]
    corpus = [
        {"id": "doc-1", "text": "the delivery deadline is strict"},
        {"id": "doc-2", "text": "budget line only"},
    ]
    report = await runner.evaluate_search(samples=samples, corpus=corpus, strategy="baseline", top_k=3)

    assert report["samples"] == 1
    assert report["strategy"] == "baseline"
    assert report["mean_recall_at_k"] == 1.0
    assert len(report["rows"]) == 1
    assert report["mean_latency_ms"] >= 0.0
    assert report["rows"][0]["relevant_items"][0]["id"] == "doc-1"
    assert report["rows"][0]["retrieved_items"][0]["text"] == "the delivery deadline is strict"


@pytest.mark.asyncio
async def test_evaluate_search_semantic():
    runner = EvaluationRunner(search_pipeline=_FakeSearchPipeline())
    samples = [
        SearchEvalSample(
            sample_id="s1",
            query="delivery deadline",
            relevant_ids={"doc-1"},
            relevance_by_id={"doc-1": 2.0},
        )
    ]
    report = await runner.evaluate_search(
        samples=samples,
        corpus=[{"id": "doc-1", "text": "the delivery deadline is strict", "metadata": {"page": 1}}],
        strategy="semantic",
        top_k=3,
    )

    assert report["strategy"] == "semantic"
    assert report["mean_mrr"] == 1.0
    assert report["mean_latency_ms"] == 12.0
    assert report["rows"][0]["retrieved_items"][0]["metadata"]["page"] == 1
    assert report["rows"][0]["relevant_items"][0]["text"] == "the delivery deadline is strict"


def test_evaluate_detection_and_economics():
    runner = EvaluationRunner(search_pipeline=_FakeSearchPipeline())
    detection = runner.evaluate_detection(
        gold_labels=[True, False, True],
        predicted_labels=[True, False, False],
    )
    economics = runner.evaluate_economics(
        [{"prompt_tokens": 10, "completion_tokens": 5, "latency_ms": 100, "compression_ratio": 0.6, "llm_calls": 1}]
    )

    assert detection["precision"] == 1.0
    assert detection["recall"] == 0.5
    assert economics["total_tokens"] == 15.0


@pytest.mark.asyncio
async def test_evaluate_search_strategies():
    runner = EvaluationRunner(search_pipeline=_FakeSearchPipeline())
    samples = [
        SearchEvalSample(
            sample_id="s1",
            query="delivery deadline",
            relevant_ids={"doc-1"},
            relevance_by_id={"doc-1": 2.0},
        )
    ]
    corpus = [{"id": "doc-1", "text": "delivery deadline approved"}]
    result = await runner.evaluate_search_strategies(
        samples=samples,
        corpus=corpus,
        strategies=["baseline", "semantic"],
        top_k=3,
    )

    assert result["strategies"] == ["baseline", "semantic"]
    assert "baseline" in result["reports"]
    assert "semantic" in result["reports"]
    assert result["best_strategy_by_recall"] in {"baseline", "semantic"}


@pytest.mark.asyncio
async def test_run_find_experiment(monkeypatch):
    fake_pipeline = _FakeSearchPipeline()
    runner = EvaluationRunner(search_pipeline=fake_pipeline)

    def _fake_pack(*args, **kwargs):
        assert kwargs["max_query_chars"] == 2048
        return {
            "dataset_name": "kensho/FIND",
            "split": "validation",
            "samples_count": 1,
            "corpus_count": 1,
            "skipped_too_long_queries": 0,
            "max_query_chars": 2048,
            "samples": [
                SearchEvalSample(
                    sample_id="s1",
                    query="delivery deadline",
                    relevant_ids={"doc-1"},
                    relevance_by_id={"doc-1": 1.0},
                )
            ],
            "corpus": [{"id": "doc-1", "text": "delivery deadline approved"}],
        }

    monkeypatch.setattr("app.eval.runner.load_find_eval_pack", _fake_pack)

    result = await runner.run_find_experiment(
        dataset_name="kensho/FIND",
        split="validation",
        max_samples=10,
        strategies=["baseline", "semantic"],
        streaming=True,
        max_query_chars=2048,
    )

    assert result["dataset_name"] == "kensho/FIND"
    assert result["samples_count"] == 1
    assert result["max_query_chars"] == 2048
    assert "comparison" in result
    assert fake_pipeline.index_calls == [("default", 1)]


@pytest.mark.asyncio
async def test_evaluate_search_semantic_resilient_to_pipeline_error():
    runner = EvaluationRunner(search_pipeline=_FailingSearchPipeline())
    samples = [
        SearchEvalSample(
            sample_id="s1",
            query="delivery deadline",
            relevant_ids={"doc-1"},
            relevance_by_id={"doc-1": 2.0},
        )
    ]
    report = await runner.evaluate_search(samples=samples, corpus=[], strategy="semantic", top_k=3)

    assert report["strategy"] == "semantic"
    assert report["samples"] == 1
    assert report["mean_recall_at_k"] == 0.0
    assert report["rows"][0]["error"] == "remote disconnect"
