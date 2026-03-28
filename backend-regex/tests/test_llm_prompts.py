"""Tests for LLM prompt builders."""

from app.llm.prompts import (
    build_detection_prompt,
    build_explanation_prompt,
    build_summary_prompt,
)


def test_build_detection_prompt_contains_key_sections():
    prompt = build_detection_prompt(
        claim="Budget is 1200 EUR",
        context="Evidence says 900 EUR",
        conflicts=[{"type": "amount_conflict"}],
    )
    assert "Claim:" in prompt
    assert "Evidence Context:" in prompt
    assert "amount_conflict" in prompt


def test_build_explanation_and_summary_prompts():
    explanation = build_explanation_prompt({"severity": "high"})
    summary = build_summary_prompt([{"document_id": "doc-1"}])
    assert "severity" in explanation
    assert "doc-1" in summary

