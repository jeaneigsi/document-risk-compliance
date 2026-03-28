"""Tests for detection pipeline."""

from app.detect.pipeline import DetectionPipeline


def test_detection_pipeline_runs_and_returns_decision():
    class _FakeLLM:
        def analyze_sync(self, prompt: str, model: str | None = None, temperature: float = 0.0, max_tokens: int | None = None):
            return {
                "status": "completed",
                "model": model or "fake",
                "content": "inconsistent",
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }

    pipeline = DetectionPipeline(llm_client=_FakeLLM())
    result = pipeline.run(
        document_id="doc-1",
        claims=[
            "Le budget approuvé est de 1200 EUR au 2026-03-25",
            "Référence REF-AAA01",
        ],
        markdown="Budget final: 900 EUR\n\nDate: 2026-04-01\n\nRéférence REF-BBB02",
        layout=[],
    )

    assert result["status"] == "completed"
    assert result["document_id"] == "doc-1"
    assert result["claims_count"] == 2
    assert result["conflict_count"] >= 2
    assert result["severity"] in {"medium", "high", "critical"}
    assert isinstance(result["recommendation"], str)
    assert isinstance(result["results"], list)
    assert result["results"][0]["llm_analysis"] is not None
    assert "latency_ms" in result
    assert "economics" in result
    assert result["economics"]["llm_calls_count"] >= 1
