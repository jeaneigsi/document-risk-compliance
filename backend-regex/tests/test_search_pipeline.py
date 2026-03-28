"""Tests for search pipeline orchestration."""

import pytest

from app.search.pipeline import SearchPipeline


class _FakeClient:
    async def search(self, query: str, index_name: str, top_k: int):
        assert query == "deadline"
        assert index_name == "contracts"
        assert top_k == 3
        return [
            {"id": "2", "score": 0.4},
            {"id": "1", "score": 0.8},
        ]

    async def index_evidence_units(self, evidence_units, index_name: str):
        return {"status": "ok", "indexed_count": len(evidence_units), "index_name": index_name}


class _FailingSearchClient(_FakeClient):
    async def search(self, query: str, index_name: str, top_k: int):
        raise RuntimeError("nextplaid disconnected")


class _HybridSearchClient(_FakeClient):
    async def search(self, query: str, index_name: str, top_k: int):
        assert top_k == 9
        return [
            {"id": "sem-1", "score": 0.9},
            {"id": "sem-2", "score": 0.7},
        ]


class _FakeRegistry:
    def lexical_search(self, index_name: str, query: str, top_k: int = 10):
        return [{"id": "lex-1", "score": 0.5, "text": "deadline clause"}]

    def rg_search(self, index_name: str, query: str, top_k: int = 10):
        assert index_name == "contracts"
        assert query == "deadline"
        assert top_k == 3
        return [{"id": "rg-1", "score": 0.9, "text": "deadline is tomorrow"}]


@pytest.mark.asyncio
async def test_search_pipeline_run():
    pipeline = SearchPipeline(client=_FakeClient())
    result = await pipeline.run(query="deadline", index_name="contracts", top_k=3, strategy="semantic")

    assert result["status"] == "completed"
    assert result["strategy"] == "semantic"
    assert result["count"] == 2
    assert result["results"][0]["id"] == "1"
    assert "latency_ms" in result
    assert "candidate_count" in result
    assert "candidate_kept_count" in result


@pytest.mark.asyncio
async def test_search_pipeline_index_evidence_units():
    from app.search.evidence import EvidenceUnit

    pipeline = SearchPipeline(client=_FakeClient())
    result = await pipeline.index_evidence_units(
        evidence_units=[
            EvidenceUnit(evidence_id="ev-1", document_id="doc-1", content="hello"),
            EvidenceUnit(evidence_id="ev-2", document_id="doc-1", content="world"),
        ],
        index_name="contracts",
    )

    assert result["status"] == "completed"
    assert result["indexed_count"] == 2
    assert result["index_name"] == "contracts"


@pytest.mark.asyncio
async def test_search_pipeline_run_resilient_to_semantic_errors():
    pipeline = SearchPipeline(client=_FailingSearchClient())
    result = await pipeline.run(query="deadline", index_name="contracts", top_k=3, strategy="semantic")

    assert result["status"] == "completed"
    assert result["strategy"] == "semantic"
    assert result["count"] == 0
    assert result["candidate_count"] == 0
    assert "semantic_error" in result


@pytest.mark.asyncio
async def test_search_pipeline_run_rg_strategy():
    pipeline = SearchPipeline(client=_FakeClient(), registry=_FakeRegistry())
    result = await pipeline.run(query="deadline", index_name="contracts", top_k=3, strategy="rg")

    assert result["status"] == "completed"
    assert result["strategy"] == "rg"
    assert result["count"] == 1
    assert result["results"][0]["id"] == "rg-1"
    assert result["candidate_count"] == 1


@pytest.mark.asyncio
async def test_search_pipeline_run_hybrid_uses_internal_semantic_pool():
    pipeline = SearchPipeline(client=_HybridSearchClient(), registry=_FakeRegistry())
    result = await pipeline.run(query="deadline", index_name="contracts", top_k=3, strategy="hybrid")

    assert result["status"] == "completed"
    assert result["strategy"] == "hybrid"
    assert result["semantic_top_k_internal"] == 9
    assert result["candidate_count"] >= 2
