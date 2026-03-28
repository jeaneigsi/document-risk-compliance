"""Prompt templates for Phase 5 LLM integration."""

import json


def build_detection_prompt(
    claim: str,
    context: str,
    conflicts: list[dict],
) -> str:
    """Prompt for adjudicating inconsistency severity and rationale."""
    return (
        "You are a document consistency analyst.\n"
        "Given a claim, evidence context, and pre-detected conflicts, return a strict JSON object.\n"
        "JSON schema: "
        '{"verdict":"consistent|inconsistent|uncertain","confidence":0..1,'
        '"rationale":"short explanation","recommended_action":"..."}\n'
        f"Claim:\n{claim}\n\n"
        f"Evidence Context:\n{context}\n\n"
        f"Pre-detected conflicts:\n{json.dumps(conflicts, ensure_ascii=False)}\n"
    )


def build_explanation_prompt(result: dict) -> str:
    """Prompt to transform a detection result into a concise explanation."""
    return (
        "Summarize the inconsistency analysis below in <= 5 bullet points."
        " Highlight key conflict types, severity, and recommended action.\n\n"
        f"{json.dumps(result, ensure_ascii=False)}"
    )


def build_summary_prompt(results: list[dict]) -> str:
    """Prompt to summarize multiple detection results."""
    return (
        "Produce an executive summary from the detection outputs."
        " Keep it concise and actionable.\n\n"
        f"{json.dumps(results, ensure_ascii=False)}"
    )

