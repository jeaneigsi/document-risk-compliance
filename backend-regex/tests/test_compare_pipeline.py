from __future__ import annotations

import pytest

from app.compare.diff_engine import build_diff_engine
from app.compare.pipeline import CompareDocumentsPipeline, PreparedDocument
from app.search.evidence import EvidenceUnit


class DummySearchPipeline:
    async def index_evidence_units(self, evidence_units, index_name="default"):
        return {"status": "completed", "indexed_count": len(evidence_units)}

    async def run(self, query, index_name="default", top_k=5, strategy="hybrid", document_ids=None):
        doc_id = (document_ids or [""])[0]
        rows = {
            "left-doc": [
                {
                    "id": "left-1",
                    "score": 0.95,
                    "text": "The limitation of liability is capped at 50,000 EUR.",
                    "metadata": {"document_id": "left-doc", "page_number": 2, "bbox_2d": {"x1": 0.1, "y1": 0.1, "x2": 0.5, "y2": 0.2}},
                }
            ],
            "right-doc": [
                {
                    "id": "right-1",
                    "score": 0.96,
                    "text": "The limitation of liability is capped at 500,000 EUR.",
                    "metadata": {"document_id": "right-doc", "page_number": 2, "bbox_2d": {"x1": 0.1, "y1": 0.1, "x2": 0.5, "y2": 0.2}},
                }
            ],
            "left-ambiguous": [
                {
                    "id": "left-a",
                    "score": 0.75,
                    "text": "Termination requires prompt notice and mutual discussion.",
                    "metadata": {"document_id": "left-ambiguous", "page_number": 1},
                }
            ],
            "right-ambiguous": [
                {
                    "id": "right-a",
                    "score": 0.74,
                    "text": "Termination requires commercially reasonable notice and review.",
                    "metadata": {"document_id": "right-ambiguous", "page_number": 1},
                }
            ],
        }
        return {
            "status": "completed",
            "results": rows.get(doc_id, []),
            "candidate_count": len(rows.get(doc_id, [])),
            "latency_ms": 5.0,
            "semantic_error": None,
        }


class GuardLLMClient:
    def analyze_sync(self, *args, **kwargs):
        raise AssertionError("LLM should not be called for deterministic mismatch.")


class FallbackLLMClient:
    def analyze_sync(self, *args, **kwargs):
        return {
            "status": "completed",
            "model": "fake-model",
            "content": '{"verdict":"inconsistent","severity":"medium","confidence":0.77,"summary":"Semantic contradiction detected.","rationale":"The passages diverge on termination obligations.","evidence_used_ids":["left-a","right-a"],"structured_diffs":[]}',
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        }


def _prepared(document_id: str, text: str) -> PreparedDocument:
    return PreparedDocument(
        document_id=document_id,
        filename=f"{document_id}.pdf",
        markdown=text,
        layout=[],
        evidence_units=[
            EvidenceUnit(
                evidence_id=f"{document_id}:1",
                document_id=document_id,
                content=text,
                page_number=1,
                metadata={"filename": f"{document_id}.pdf"},
            )
        ],
    )


@pytest.mark.asyncio
async def test_compare_pipeline_uses_structured_decision_without_llm():
    pipeline = CompareDocumentsPipeline(
        search_pipeline=DummySearchPipeline(),
        llm_client=GuardLLMClient(),
    )

    result = await pipeline.analyze(
        left=_prepared("left-doc", "The limitation of liability is capped at 50,000 EUR."),
        right=_prepared("right-doc", "The limitation of liability is capped at 500,000 EUR."),
        claims=["The liability clause is materially identical in both documents."],
        strategy="hybrid",
        index_name="default",
        model=None,
    )

    issue = result["issues"][0]
    assert issue["verdict"] == "inconsistent"
    assert issue["decision_source"] == "structured_compare"
    assert issue["structured_diffs"][0]["diff_kind"] == "value_mismatch"
    assert issue["structured_diffs"][0]["lexical_diff_ops"]
    assert issue["structured_diffs"][0]["change_subtype"] == "numeric_change"
    assert issue["alignment_pairs"][0]["alignment_source"] == "hybrid"
    assert issue["retrieval"]["pair_candidate_count"] >= 1
    assert result["usage"]["total_tokens"] == 0


@pytest.mark.asyncio
async def test_compare_pipeline_escalates_to_llm_for_ambiguous_pair():
    pipeline = CompareDocumentsPipeline(
        search_pipeline=DummySearchPipeline(),
        llm_client=FallbackLLMClient(),
    )

    result = await pipeline.analyze(
        left=_prepared("left-ambiguous", "Termination requires prompt notice and mutual discussion."),
        right=_prepared("right-ambiguous", "Termination requires commercially reasonable notice and review."),
        claims=["The termination clause is materially identical in both documents."],
        strategy="hybrid",
        index_name="default",
        model=None,
    )

    issue = result["issues"][0]
    assert issue["decision_source"] == "llm"
    assert issue["verdict"] == "inconsistent"
    assert issue["alignment_pairs"][0]["pairing_reason"]
    assert issue["usage"]["total_tokens"] == 120
    assert result["summary"]["llm_escalation_count"] == 1


@pytest.mark.asyncio
async def test_compare_pipeline_diff_first_returns_changes_without_claims():
    pipeline = CompareDocumentsPipeline(
        search_pipeline=DummySearchPipeline(),
        llm_client=GuardLLMClient(),
    )

    result = await pipeline.analyze(
        left=_prepared("left-doc", "The limitation of liability is capped at 50,000 EUR."),
        right=_prepared("right-doc", "The limitation of liability is capped at 500,000 EUR."),
        strategy="lexical",
        index_name="default",
        model=None,
    )

    assert result["mode"] == "diff-first"
    assert result["changes"]
    assert result["changes"][0]["change_subtype"] == "numeric_change"
    assert result["summary"]["change_count"] >= 1


def test_diff_engine_refines_single_letter_change_inside_word():
    engine = build_diff_engine()

    ops = engine.diff_words("Supplier", "Suppller")

    assert any(item["op"] == "equal" and "Suppl" in item["text"] for item in ops)
    assert any(item["op"] == "delete" and item["text"] == "i" for item in ops)
    assert any(item["op"] == "insert" and item["text"] == "l" for item in ops)


@pytest.mark.asyncio
async def test_compare_pipeline_returns_empty_change_list_for_identical_documents():
    pipeline = CompareDocumentsPipeline(
        search_pipeline=DummySearchPipeline(),
        llm_client=GuardLLMClient(),
    )

    result = await pipeline.analyze(
        left=_prepared("same-left", "Supplier name: Contoso Manufacturing"),
        right=_prepared("same-right", "Supplier name: Contoso Manufacturing"),
        strategy="lexical",
        index_name="default",
        model=None,
    )

    assert result["mode"] == "diff-first"
    assert result["changes"] == []
    assert result["summary"]["has_changes"] is False
    assert "Aucun changement" in result["llm_summary"]
