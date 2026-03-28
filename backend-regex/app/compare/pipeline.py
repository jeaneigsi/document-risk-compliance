"""Compare two documents with retrieval-grounded structured decision cascade."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from app.compare.normalization import (
    AMOUNT_RE,
    DATE_RE,
    category_keywords,
    detect_claim_category,
    extract_facts,
    extract_section_hint,
    normalize_text,
)
from app.compare.pairing import pair_evidence_rows
from app.llm import LiteLLMClient
from app.search import SearchPipeline, EvidenceUnit, build_evidence_units_from_ocr


@dataclass
class PreparedDocument:
    document_id: str
    filename: str
    markdown: str
    layout: list
    evidence_units: list[EvidenceUnit]


class CompareDocumentsPipeline:
    """Document-to-document compare pipeline for demo and review workflows."""

    def __init__(
        self,
        search_pipeline: SearchPipeline | None = None,
        llm_client: LiteLLMClient | None = None,
    ):
        self.search_pipeline = search_pipeline or SearchPipeline()
        self.llm_client = llm_client or LiteLLMClient()

    @staticmethod
    def prepare_document(
        document_id: str,
        filename: str,
        markdown: str,
        layout: list,
    ) -> PreparedDocument:
        return PreparedDocument(
            document_id=document_id,
            filename=filename,
            markdown=markdown,
            layout=layout,
            evidence_units=build_evidence_units_from_ocr(
                document_id=document_id,
                filename=filename,
                md_results=markdown,
                layout_details=layout,
            ),
        )

    def suggest_claims(self, left: PreparedDocument, right: PreparedDocument, limit: int = 8) -> list[dict[str, Any]]:
        left_text = left.markdown or "\n".join(unit.content for unit in left.evidence_units[:200])
        right_text = right.markdown or "\n".join(unit.content for unit in right.evidence_units[:200])
        suggestions: list[dict[str, Any]] = []

        def add_suggestion(claim: str, category: str, left_value: str, right_value: str, severity: str) -> None:
            if claim in {item["claim"] for item in suggestions}:
                return
            suggestions.append(
                {
                    "claim": claim,
                    "category": category,
                    "severity_hint": severity,
                    "left_value": left_value,
                    "right_value": right_value,
                }
            )

        left_amounts = list(dict.fromkeys(match.group(0).strip() for match in AMOUNT_RE.finditer(left_text)))
        right_amounts = list(dict.fromkeys(match.group(0).strip() for match in AMOUNT_RE.finditer(right_text)))
        if left_amounts and right_amounts and left_amounts[:3] != right_amounts[:3]:
            add_suggestion(
                "The monetary terms are identical in both documents.",
                "payment",
                left_amounts[0],
                right_amounts[0],
                "high",
            )

        left_dates = list(dict.fromkeys(match.group(0).strip() for match in DATE_RE.finditer(left_text)))
        right_dates = list(dict.fromkeys(match.group(0).strip() for match in DATE_RE.finditer(right_text)))
        if left_dates and right_dates and left_dates[:3] != right_dates[:3]:
            add_suggestion(
                "The effective dates and key calendar dates are identical in both documents.",
                "effective_date",
                left_dates[0],
                right_dates[0],
                "high",
            )

        for category, keywords in {
            "liability": category_keywords("liability"),
            "termination": category_keywords("termination"),
            "governing_law": category_keywords("governing_law"),
            "confidentiality": category_keywords("confidentiality"),
        }.items():
            left_hit = self._best_keyword_block(left.evidence_units, keywords)
            right_hit = self._best_keyword_block(right.evidence_units, keywords)
            if not left_hit or not right_hit:
                continue
            left_norm = normalize_text(left_hit.content)
            right_norm = normalize_text(right_hit.content)
            if left_norm != right_norm:
                pretty = category.replace("_", " ")
                add_suggestion(
                    f"The {pretty} clause is materially identical in both documents.",
                    category,
                    left_hit.content[:240],
                    right_hit.content[:240],
                    "medium",
                )

        if not suggestions:
            add_suggestion(
                "The key contractual terms are identical in both documents.",
                "general",
                left_text[:240],
                right_text[:240],
                "medium",
            )

        return suggestions[:limit]

    async def analyze(
        self,
        left: PreparedDocument,
        right: PreparedDocument,
        claims: list[str],
        auto_diff: bool = True,
        strategy: str = "hybrid",
        index_name: str = "default",
        top_k: int = 5,
        model: str | None = None,
    ) -> dict[str, Any]:
        started = perf_counter()
        for prepared in (left, right):
            if prepared.evidence_units:
                try:
                    await self.search_pipeline.index_evidence_units(
                        evidence_units=prepared.evidence_units,
                        index_name=index_name,
                    )
                except Exception:
                    pass

        suggestion_rows = self.suggest_claims(left, right)
        suggestion_claims = [row["claim"] for row in suggestion_rows]
        requested_claims = [item.strip() for item in claims if item and item.strip()]
        claim_list = requested_claims[:]
        if auto_diff:
            for claim in suggestion_claims:
                if claim not in claim_list:
                    claim_list.append(claim)
        claim_list = claim_list[:12]

        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        issues: list[dict[str, Any]] = []
        for index, claim in enumerate(claim_list, start=1):
            issue_started = perf_counter()
            category = detect_claim_category(claim)
            left_retrieval = await self._retrieve_for_document(
                document=left,
                claim=claim,
                strategy=strategy,
                index_name=index_name,
                top_k=top_k,
            )
            right_retrieval = await self._retrieve_for_document(
                document=right,
                claim=claim,
                strategy=strategy,
                index_name=index_name,
                top_k=top_k,
            )
            pairs = pair_evidence_rows(
                claim=claim,
                category=category,
                left_rows=left_retrieval["evidence"],
                right_rows=right_retrieval["evidence"],
                max_pairs=max(2, min(4, top_k)),
            )
            local_decision = self._decide_from_pairs(claim=claim, category=category, pairs=pairs)

            usage: dict[str, Any] = {}
            raw_content = ""
            verdict = local_decision["verdict"]
            severity = local_decision["severity"]
            confidence = local_decision["confidence"]
            summary = local_decision["summary"]
            rationale = local_decision["rationale"]
            evidence_used_ids = local_decision["evidence_used_ids"]
            structured_diffs = local_decision["structured_diffs"]
            decision_source = local_decision["decision_source"]
            ambiguity_reason = local_decision.get("ambiguity_reason")

            if local_decision["needs_llm"]:
                prompt = self._build_compare_prompt(
                    claim=claim,
                    category=category,
                    pairs=pairs,
                    local_decision=local_decision,
                )
                llm_result = self.llm_client.analyze_sync(
                    prompt=prompt,
                    model=model,
                    temperature=0.0,
                    max_tokens=1200,
                )
                usage = llm_result.get("usage", {}) or {}
                raw_content = llm_result.get("content", "") or ""
                parsed = self._parse_compare_json(raw_content)
                verdict = parsed.get("verdict", verdict)
                severity = parsed.get("severity", severity)
                confidence = parsed.get("confidence", confidence)
                summary = parsed.get("summary") or parsed.get("rationale") or summary
                rationale = parsed.get("rationale") or parsed.get("summary") or rationale
                evidence_used_ids = parsed.get("evidence_used_ids", evidence_used_ids)
                structured_diffs = parsed.get("structured_diffs") or structured_diffs
                decision_source = "llm"
                ambiguity_reason = ambiguity_reason or "local_decision_uncertain"
                total_usage["prompt_tokens"] += int(usage.get("prompt_tokens", 0))
                total_usage["completion_tokens"] += int(usage.get("completion_tokens", 0))
                total_usage["total_tokens"] += int(
                    usage.get("total_tokens", 0)
                    or (int(usage.get("prompt_tokens", 0)) + int(usage.get("completion_tokens", 0)))
                )

            issue = {
                "issue_id": f"issue-{index}",
                "claim": claim,
                "category": category,
                "verdict": verdict,
                "severity": severity,
                "confidence": confidence,
                "summary": summary,
                "rationale": rationale,
                "decision_source": decision_source,
                "evidence_quality": local_decision["evidence_quality"],
                "ambiguity_reason": ambiguity_reason,
                "structured_diffs": structured_diffs,
                "left_evidence": left_retrieval["evidence"],
                "right_evidence": right_retrieval["evidence"],
                "evidence_used_ids": evidence_used_ids,
                "suggested": claim in suggestion_claims and claim not in requested_claims,
                "usage": usage,
                "latency_ms": round((perf_counter() - issue_started) * 1000.0, 3),
                "raw_content": raw_content,
                "retrieval": {
                    "strategy": strategy,
                    "left_mode": left_retrieval["mode"],
                    "right_mode": right_retrieval["mode"],
                    "candidate_count": left_retrieval["candidate_count"] + right_retrieval["candidate_count"],
                    "pair_candidate_count": len(pairs),
                    "best_pair_reason": pairs[0]["pairing_reason"] if pairs else None,
                    "evidence_kept_count": len(left_retrieval["evidence"]) + len(right_retrieval["evidence"]),
                    "semantic_error": left_retrieval.get("semantic_error") or right_retrieval.get("semantic_error"),
                    "latency_ms": round(left_retrieval["latency_ms"] + right_retrieval["latency_ms"], 3),
                },
            }
            issues.append(issue)

        inconsistent_count = sum(1 for issue in issues if issue["verdict"] == "inconsistent")
        warning_count = sum(1 for issue in issues if issue["verdict"] == "insufficient_evidence")
        return {
            "status": "completed",
            "left_document_id": left.document_id,
            "right_document_id": right.document_id,
            "claims_count": len(claim_list),
            "auto_diff_enabled": auto_diff,
            "strategy": strategy,
            "index_name": index_name,
            "top_k": top_k,
            "suggestions": suggestion_rows,
            "issues": issues,
            "summary": {
                "inconsistent_count": inconsistent_count,
                "insufficient_evidence_count": warning_count,
                "consistent_count": sum(1 for issue in issues if issue["verdict"] == "consistent"),
                "latency_ms": round((perf_counter() - started) * 1000.0, 3),
                "llm_escalation_count": sum(1 for issue in issues if issue["decision_source"] == "llm"),
            },
            "usage": total_usage,
        }

    async def _retrieve_for_document(
        self,
        document: PreparedDocument,
        claim: str,
        strategy: str,
        index_name: str,
        top_k: int,
    ) -> dict[str, Any]:
        started = perf_counter()
        result = await self.search_pipeline.run(
            query=claim,
            index_name=index_name,
            top_k=top_k,
            strategy=strategy,
            document_ids=[document.document_id],
        )
        evidence = [self._build_evidence_row(row) for row in result.get("results", [])]
        if evidence:
            return {
                "mode": "indexed",
                "evidence": evidence,
                "candidate_count": int(result.get("candidate_count", len(evidence))),
                "semantic_error": result.get("semantic_error"),
                "latency_ms": float(result.get("latency_ms", 0.0)),
            }

        local_rows = self._local_fallback(document.evidence_units, claim, top_k)
        return {
            "mode": "local_fallback",
            "evidence": local_rows,
            "candidate_count": len(local_rows),
            "semantic_error": result.get("semantic_error"),
            "latency_ms": round((perf_counter() - started) * 1000.0, 3),
        }

    @staticmethod
    def _build_evidence_row(row: dict[str, Any]) -> dict[str, Any]:
        text = row.get("text") or ""
        metadata = row.get("metadata", {}) or {}
        return {
            "id": row.get("id"),
            "score": float(row.get("score", 0.0)),
            "text": text,
            "metadata": metadata,
            "section_hint": extract_section_hint(text),
            "facts": [fact.to_dict() for fact in extract_facts(text)],
        }

    @staticmethod
    def _local_fallback(units: list[EvidenceUnit], claim: str, top_k: int) -> list[dict[str, Any]]:
        normalized_terms = {token for token in re.findall(r"[a-z0-9]+", claim.lower()) if token}
        rows: list[dict[str, Any]] = []
        for unit in units:
            text = unit.content or ""
            haystack = text.lower()
            hit_count = sum(1 for term in normalized_terms if term in haystack)
            if hit_count == 0:
                continue
            score = hit_count / max(1, len(normalized_terms))
            rows.append(
                {
                    "id": unit.evidence_id,
                    "score": round(score, 6),
                    "text": text,
                    "metadata": {
                        "document_id": unit.document_id,
                        "page_number": unit.page_number,
                        "source_type": unit.source_type,
                        **unit.metadata,
                    },
                    "section_hint": extract_section_hint(text),
                    "facts": [fact.to_dict() for fact in extract_facts(text)],
                }
            )
        rows.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
        return rows[:top_k]

    def _decide_from_pairs(self, claim: str, category: str, pairs: list[dict[str, Any]]) -> dict[str, Any]:
        if not pairs:
            return self._empty_local_decision("No candidate pairs were retrieved for this claim.")

        best_pair = pairs[0]
        left_row = best_pair["left"]["row"]
        right_row = best_pair["right"]["row"]
        left_text = left_row.get("text", "")
        right_text = right_row.get("text", "")
        left_facts = best_pair["left"]["facts"]
        right_facts = best_pair["right"]["facts"]
        structured_diffs = self._build_structured_diffs(category, left_facts, right_facts)
        evidence_used_ids = [item for item in (left_row.get("id"), right_row.get("id")) if item]

        if structured_diffs:
            trusted_diffs = [
                diff for diff in structured_diffs
                if diff["field_type"] in self.TRUSTED_STRUCTURED_FIELDS
            ]
            if trusted_diffs and any(diff["diff_kind"] == "value_mismatch" for diff in trusted_diffs):
                severity = self._severity_for_category(category)
                summary = f"{category.replace('_', ' ').title()} mismatch detected between the two documents."
                return {
                    "verdict": "inconsistent",
                    "severity": severity,
                    "confidence": 0.93,
                    "summary": summary,
                    "rationale": summary,
                    "decision_source": "structured_compare",
                    "structured_diffs": structured_diffs,
                    "evidence_used_ids": evidence_used_ids,
                    "needs_llm": False,
                    "evidence_quality": "high",
                    "ambiguity_reason": None,
                }
            if trusted_diffs and all(diff["diff_kind"] == "match" for diff in trusted_diffs):
                summary = f"{category.replace('_', ' ').title()} values are aligned across both documents."
                return {
                    "verdict": "consistent",
                    "severity": "low",
                    "confidence": 0.9,
                    "summary": summary,
                    "rationale": summary,
                    "decision_source": "structured_compare",
                    "structured_diffs": structured_diffs,
                    "evidence_used_ids": evidence_used_ids,
                    "needs_llm": False,
                    "evidence_quality": "high",
                    "ambiguity_reason": None,
                }
            if any(diff["diff_kind"] == "value_mismatch" for diff in structured_diffs):
                return {
                    "verdict": "insufficient_evidence",
                    "severity": "medium",
                    "confidence": 0.45,
                    "summary": "The retrieved clauses diverge, but the difference is qualitative and needs semantic arbitration.",
                    "rationale": "Escalating to LLM because the passages disagree without a reliable structured field mismatch.",
                    "decision_source": "rule",
                    "structured_diffs": structured_diffs,
                    "evidence_used_ids": evidence_used_ids,
                    "needs_llm": True,
                    "evidence_quality": "medium",
                    "ambiguity_reason": "qualitative_clause_difference",
                }

        left_norm = normalize_text(left_text)
        right_norm = normalize_text(right_text)
        if left_norm and right_norm and left_norm == right_norm:
            return {
                "verdict": "consistent",
                "severity": "low",
                "confidence": 0.82,
                "summary": "The retrieved passages are textually identical.",
                "rationale": "The best left/right evidence blocks match after normalization.",
                "decision_source": "rule",
                "structured_diffs": structured_diffs,
                "evidence_used_ids": evidence_used_ids,
                "needs_llm": False,
                "evidence_quality": "medium",
                "ambiguity_reason": None,
            }

        if category != "general" and (left_facts or right_facts):
            return {
                "verdict": "insufficient_evidence",
                "severity": "medium",
                "confidence": 0.45,
                "summary": "Comparable evidence was retrieved but not enough structured facts matched for a deterministic verdict.",
                "rationale": "Escalating to LLM because the retrieved passages belong to the right topic but remain ambiguous.",
                "decision_source": "rule",
                "structured_diffs": structured_diffs,
                "evidence_used_ids": evidence_used_ids,
                "needs_llm": True,
                "evidence_quality": "medium",
                "ambiguity_reason": "matching_topic_but_no_clear_structured_alignment",
            }

        if not left_text or not right_text:
            return self._empty_local_decision("One side has no usable evidence for this claim.")

        return {
            "verdict": "insufficient_evidence",
            "severity": "medium",
            "confidence": 0.4,
            "summary": "The claim requires semantic arbitration.",
            "rationale": "No deterministic structured mismatch was found, but the passages are not close enough to conclude safely.",
            "decision_source": "rule",
            "structured_diffs": structured_diffs,
            "evidence_used_ids": evidence_used_ids,
            "needs_llm": True,
            "evidence_quality": "low",
            "ambiguity_reason": "textual_divergence_requires_semantic_judgement",
        }

    @staticmethod
    def _empty_local_decision(reason: str) -> dict[str, Any]:
        return {
            "verdict": "insufficient_evidence",
            "severity": "medium",
            "confidence": 0.2,
            "summary": reason,
            "rationale": reason,
            "decision_source": "rule",
            "structured_diffs": [],
            "evidence_used_ids": [],
            "needs_llm": False,
            "evidence_quality": "low",
            "ambiguity_reason": "no_candidate_pairs",
        }

    @staticmethod
    def _build_structured_diffs(category: str, left_facts: list[dict[str, Any]], right_facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if category == "general":
            comparable_types = (
                {fact["field_type"] for fact in left_facts}
                & {fact["field_type"] for fact in right_facts}
            )
        else:
            comparable_types = (
                {
                    fact["field_type"]
                    for fact in left_facts
                    if fact.get("category") == category or fact.get("field_type") in {"amount", "date", "duration"}
                }
                & {
                    fact["field_type"]
                    for fact in right_facts
                    if fact.get("category") == category or fact.get("field_type") in {"amount", "date", "duration"}
                }
            )

        rows: list[dict[str, Any]] = []
        for field_type in sorted(comparable_types):
            left_fact = next((fact for fact in left_facts if fact["field_type"] == field_type), None)
            right_fact = next((fact for fact in right_facts if fact["field_type"] == field_type), None)
            if not left_fact or not right_fact:
                continue
            rows.append(
                {
                    "field_type": field_type,
                    "left_raw": left_fact["raw_value"],
                    "right_raw": right_fact["raw_value"],
                    "left_normalized": left_fact["normalized_value"],
                    "right_normalized": right_fact["normalized_value"],
                    "diff_kind": "match"
                    if left_fact["normalized_value"] == right_fact["normalized_value"]
                    else "value_mismatch",
                }
            )
        return rows

    @staticmethod
    def _severity_for_category(category: str) -> str:
        if category in {"liability", "effective_date", "payment"}:
            return "high"
        if category in {"termination", "governing_law"}:
            return "medium"
        return "medium"

    @staticmethod
    def _build_compare_prompt(
        claim: str,
        category: str,
        pairs: list[dict[str, Any]],
        local_decision: dict[str, Any],
    ) -> str:
        if not pairs:
            return (
                "You are a document compliance analyst.\n"
                "No evidence pairs were retrieved. Return strict JSON with keys: "
                "verdict, severity, confidence, summary, rationale, evidence_used_ids, structured_diffs.\n"
                f"CLAIM:\n{claim}\n"
            )

        selected_pairs = pairs[:2]
        pair_blocks = []
        for idx, pair in enumerate(selected_pairs, start=1):
            left_row = pair["left"]["row"]
            right_row = pair["right"]["row"]
            pair_blocks.append(
                f"PAIR {idx} score={pair['pair_score']} reason={pair['pairing_reason']}\n"
                f"LEFT id={left_row.get('id')} page={((left_row.get('metadata') or {}).get('page_number'))}\n{left_row.get('text', '')}\n\n"
                f"RIGHT id={right_row.get('id')} page={((right_row.get('metadata') or {}).get('page_number'))}\n{right_row.get('text', '')}"
            )

        return (
            "You are a document compliance analyst comparing two related documents.\n"
            "Use the structured diffs and the evidence pairs below.\n"
            "Return strict JSON with keys: verdict, severity, confidence, summary, rationale, evidence_used_ids, structured_diffs.\n"
            "Allowed verdict values: inconsistent, consistent, insufficient_evidence.\n"
            "Allowed severity values: low, medium, high, critical.\n\n"
            f"CLAIM:\n{claim}\n\n"
            f"CATEGORY:\n{category}\n\n"
            f"LOCAL_DECISION_HINT:\n{json.dumps(local_decision, ensure_ascii=False)}\n\n"
            f"EVIDENCE_PAIRS:\n{chr(10).join(pair_blocks)}\n"
        )

    @staticmethod
    def _parse_compare_json(content: str | None) -> dict[str, Any]:
        safe_content = content or ""
        try:
            return json.loads(safe_content)
        except Exception:
            match = re.search(r"\{.*\}", safe_content, flags=re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except Exception:
                    pass
        return {
            "verdict": "insufficient_evidence",
            "severity": "medium",
            "confidence": None,
            "summary": safe_content.strip()[:500],
            "rationale": safe_content.strip()[:1000],
            "evidence_used_ids": [],
            "structured_diffs": [],
        }

    @staticmethod
    def _best_keyword_block(units: list[EvidenceUnit], keywords: tuple[str, ...]) -> EvidenceUnit | None:
        best: EvidenceUnit | None = None
        best_score = 0
        for unit in units:
            haystack = unit.content.lower()
            score = sum(1 for keyword in keywords if keyword in haystack)
            if score > best_score:
                best = unit
                best_score = score
        return best
    TRUSTED_STRUCTURED_FIELDS = {"amount", "date", "duration", "reference", "jurisdiction"}
