"""Compare two documents with retrieval-grounded structured decision cascade."""

from __future__ import annotations

import asyncio
import difflib
import json
import re
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from app.compare.diff_engine import LexicalDiffEngine, build_diff_engine
from app.compare.normalization import (
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

    TRUSTED_STRUCTURED_FIELDS = {"amount", "date", "duration", "reference", "jurisdiction"}
    DIFF_FIRST_SEMANTIC_REPAIR_TOP_K = 2

    def __init__(
        self,
        search_pipeline: SearchPipeline | None = None,
        llm_client: LiteLLMClient | None = None,
        diff_engine: LexicalDiffEngine | None = None,
    ):
        self.search_pipeline = search_pipeline or SearchPipeline()
        self.llm_client = llm_client or LiteLLMClient()
        self.diff_engine = diff_engine or build_diff_engine()

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

    async def analyze(
        self,
        left: PreparedDocument,
        right: PreparedDocument,
        claims: list[str] | None = None,
        strategy: str = "hybrid",
        index_name: str = "default",
        model: str | None = None,
    ) -> dict[str, Any]:
        started = perf_counter()
        requested_claims = [item.strip() for item in (claims or []) if item and item.strip()]
        if requested_claims:
            return await self._analyze_claim_driven(
                left=left,
                right=right,
                requested_claims=requested_claims,
                strategy=strategy,
                index_name=index_name,
                model=model,
                started=started,
            )
        return await self._analyze_diff_first(
            left=left,
            right=right,
            strategy=strategy,
            index_name=index_name,
            model=model,
            started=started,
        )

    async def _analyze_claim_driven(
        self,
        left: PreparedDocument,
        right: PreparedDocument,
        requested_claims: list[str],
        strategy: str,
        index_name: str,
        model: str | None,
        started: float,
    ) -> dict[str, Any]:
        claim_list = requested_claims[:8]
        retrieval_top_k = 3
        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        issues: list[dict[str, Any]] = []

        for index, claim in enumerate(claim_list, start=1):
            issue_started = perf_counter()
            category = detect_claim_category(claim)
            left_retrieval, right_retrieval = await asyncio.gather(
                self._retrieve_for_document(
                    document=left,
                    claim=claim,
                    strategy=strategy,
                    index_name=index_name,
                    top_k=retrieval_top_k,
                ),
                self._retrieve_for_document(
                    document=right,
                    claim=claim,
                    strategy=strategy,
                    index_name=index_name,
                    top_k=retrieval_top_k,
                ),
            )
            pairs = pair_evidence_rows(
                claim=claim,
                category=category,
                left_rows=left_retrieval["evidence"],
                right_rows=right_retrieval["evidence"],
                max_pairs=3,
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
                    max_tokens=700,
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

            issues.append(
                {
                    "issue_id": f"issue-{index}",
                    "claim": claim,
                    "category": category,
                    "business_type": category,
                    "verdict": verdict,
                    "severity": severity,
                    "confidence": confidence,
                    "summary": summary,
                    "rationale": rationale,
                    "decision_source": decision_source,
                    "alignment_pairs": self._serialize_alignment_pairs(pairs=pairs, strategy=strategy),
                    "evidence_quality": local_decision["evidence_quality"],
                    "ambiguity_reason": ambiguity_reason,
                    "structured_diffs": structured_diffs,
                    "left_evidence": left_retrieval["evidence"],
                    "right_evidence": right_retrieval["evidence"],
                    "evidence_used_ids": evidence_used_ids,
                    "suggested": False,
                    "usage": usage,
                    "latency_ms": round((perf_counter() - issue_started) * 1000.0, 3),
                    "raw_content": raw_content,
                    "retrieval": {
                        "strategy": strategy,
                        "left_mode": left_retrieval["mode"],
                        "right_mode": right_retrieval["mode"],
                        "candidate_count": left_retrieval["candidate_count"] + right_retrieval["candidate_count"],
                        "pair_candidate_count": len(pairs),
                        "semantic_rerank_count": max(0, len(pairs) - 1) if strategy in {"semantic", "hybrid"} else 0,
                        "best_pair_reason": pairs[0]["pairing_reason"] if pairs else None,
                        "evidence_kept_count": len(left_retrieval["evidence"]) + len(right_retrieval["evidence"]),
                        "semantic_error": left_retrieval.get("semantic_error") or right_retrieval.get("semantic_error"),
                        "latency_ms": round(left_retrieval["latency_ms"] + right_retrieval["latency_ms"], 3),
                    },
                }
            )

        inconsistent_count = sum(1 for issue in issues if issue["verdict"] == "inconsistent")
        warning_count = sum(1 for issue in issues if issue["verdict"] == "insufficient_evidence")
        return {
            "status": "completed",
            "mode": "claim-driven",
            "left_document_id": left.document_id,
            "right_document_id": right.document_id,
            "claims_count": len(claim_list),
            "strategy": strategy,
            "index_name": index_name,
            "changes": [],
            "groups": [],
            "llm_summary": "",
            "issues": issues,
            "summary": {
                "inconsistent_count": inconsistent_count,
                "insufficient_evidence_count": warning_count,
                "consistent_count": sum(1 for issue in issues if issue["verdict"] == "consistent"),
                "change_count": 0,
                "latency_ms": round((perf_counter() - started) * 1000.0, 3),
                "llm_escalation_count": sum(1 for issue in issues if issue["decision_source"] == "llm"),
            },
            "usage": total_usage,
        }

    async def _analyze_diff_first(
        self,
        left: PreparedDocument,
        right: PreparedDocument,
        strategy: str,
        index_name: str,
        model: str | None,
        started: float,
    ) -> dict[str, Any]:
        changes = await self._discover_changes(
            left=left,
            right=right,
            strategy=strategy,
            index_name=index_name,
        )
        llm_summary = "Aucun changement significatif détecté."
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        if changes:
            llm_summary, usage = self._summarize_changes(changes=changes, model=model)
        groups = self._group_changes(changes)
        return {
            "status": "completed",
            "mode": "diff-first",
            "left_document_id": left.document_id,
            "right_document_id": right.document_id,
            "strategy": strategy,
            "index_name": index_name,
            "changes": changes,
            "groups": groups,
            "llm_summary": llm_summary,
            "summary": {
                "has_changes": bool(changes),
                "change_count": len(changes),
                "latency_ms": round((perf_counter() - started) * 1000.0, 3),
                "llm_escalation_count": 1 if llm_summary else 0,
            },
            "usage": usage,
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
        structured_diffs = self._build_structured_diffs(category, left_facts, right_facts, left_text=left_text, right_text=right_text)
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

    def _build_structured_diffs(
        self,
        category: str,
        left_facts: list[dict[str, Any]],
        right_facts: list[dict[str, Any]],
        left_text: str,
        right_text: str,
    ) -> list[dict[str, Any]]:
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
            lexical_diff_ops = self.diff_engine.diff_words(left_fact["raw_value"], right_fact["raw_value"])
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
                    "lexical_diff_ops": lexical_diff_ops,
                    "change_subtype": self.diff_engine.classify_change(
                        left_fact["raw_value"],
                        right_fact["raw_value"],
                        lexical_diff_ops,
                    ),
                    "changed_tokens_count": self._count_changed_tokens(lexical_diff_ops),
                }
            )
        if not rows and left_text and right_text:
            lexical_diff_ops = self.diff_engine.diff_words(left_text, right_text)
            if lexical_diff_ops:
                rows.append(
                    {
                        "field_type": "block_text",
                        "left_raw": left_text,
                        "right_raw": right_text,
                        "left_normalized": normalize_text(left_text),
                        "right_normalized": normalize_text(right_text),
                        "diff_kind": "match" if normalize_text(left_text) == normalize_text(right_text) else "value_mismatch",
                        "lexical_diff_ops": lexical_diff_ops,
                        "change_subtype": self.diff_engine.classify_change(left_text, right_text, lexical_diff_ops),
                        "changed_tokens_count": self._count_changed_tokens(lexical_diff_ops),
                    }
                )
        return rows

    @staticmethod
    def _rows_for_auto_diff(units: list[EvidenceUnit], limit: int = 16) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for index, unit in enumerate(units):
            text = (unit.content or "").strip()
            if len(text) < 8:
                continue
            metadata = unit.metadata or {}
            page_number = int(unit.page_number or metadata.get("page_number") or 0)
            section_hint = extract_section_hint(text)
            base_score = round(max(0.05, 1.0 - (index * 0.03)), 6)
            rows.append(
                {
                    "id": unit.evidence_id,
                    "parent_id": unit.evidence_id,
                    "row_type": "block",
                    "score": base_score,
                    "text": text,
                    "metadata": {
                        **metadata,
                        "page_number": page_number,
                    },
                    "page_number": page_number,
                    "section_hint": section_hint,
                    "facts": [fact.to_dict() for fact in extract_facts(text)],
                    "normalized_text": normalize_text(text),
                }
            )
            for sent_index, sentence in enumerate(CompareDocumentsPipeline._split_sentences(text)[:2], start=1):
                if len(rows) >= limit:
                    break
                sentence = sentence.strip()
                if len(sentence) < 18:
                    continue
                rows.append(
                    {
                        "id": f"{unit.evidence_id}:s{sent_index}",
                        "parent_id": unit.evidence_id,
                        "row_type": "sentence",
                        "score": round(max(0.04, base_score - (sent_index * 0.08)), 6),
                        "text": sentence,
                        "metadata": {
                            **metadata,
                            "page_number": page_number,
                        },
                        "page_number": page_number,
                        "section_hint": section_hint,
                        "facts": [fact.to_dict() for fact in extract_facts(sentence)],
                        "normalized_text": normalize_text(sentence),
                    }
                )
            if len(rows) >= limit:
                break
        return rows

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        return [chunk.strip() for chunk in re.split(r"(?<=[.!?;:])\s+|\n+", text or "") if chunk.strip()]

    async def _discover_changes(
        self,
        left: PreparedDocument,
        right: PreparedDocument,
        strategy: str,
        index_name: str,
    ) -> list[dict[str, Any]]:
        left_rows = self._rows_for_auto_diff(left.evidence_units, limit=18)
        right_rows = self._rows_for_auto_diff(right.evidence_units, limit=18)
        if not left_rows or not right_rows:
            return []

        changes: list[dict[str, Any]] = []
        seen_keys: set[tuple[str, str, str, str, str]] = set()
        matched_left: set[str] = set()
        matched_right: set[str] = set()
        semantic_budget = 4 if strategy in {"semantic", "hybrid"} else 0
        compare_count = min(len(left_rows), len(right_rows), 12)

        for index in range(compare_count):
            left_row = left_rows[index]
            right_candidates = self._candidate_right_rows(left_row, right_rows, index)
            pairs = pair_evidence_rows(
                claim="document difference",
                category="general",
                left_rows=[left_row],
                right_rows=right_candidates,
                max_pairs=1,
            )
            best_pair = pairs[0] if pairs else None

            if (
                semantic_budget > 0
                and strategy in {"semantic", "hybrid"}
                and (best_pair is None or float(best_pair.get("pair_score", 0.0)) < 2.2)
            ):
                semantic_budget -= 1
                semantic_candidates = await self._semantic_alignment_candidates(
                    document=right,
                    source_row=left_row,
                    index_name=index_name,
                    top_k=self.DIFF_FIRST_SEMANTIC_REPAIR_TOP_K,
                )
                if semantic_candidates:
                    pairs = pair_evidence_rows(
                        claim="document difference",
                        category="general",
                        left_rows=[left_row],
                        right_rows=self._merge_candidate_rows(right_candidates, semantic_candidates),
                        max_pairs=1,
                    )
                    best_pair = pairs[0] if pairs else best_pair

            if not best_pair:
                continue

            left_text = best_pair["left"]["row"].get("text", "")
            right_text = best_pair["right"]["row"].get("text", "")
            if normalize_text(left_text) == normalize_text(right_text):
                matched_left.add(best_pair["left"]["row"].get("id", ""))
                matched_right.add(best_pair["right"]["row"].get("id", ""))
                continue

            structured_diffs = self._build_structured_diffs(
                category="general",
                left_facts=best_pair["left"].get("facts", []),
                right_facts=best_pair["right"].get("facts", []),
                left_text=left_text,
                right_text=right_text,
            )
            diff = next((row for row in structured_diffs if row.get("diff_kind") == "value_mismatch"), None)
            if not diff:
                continue
            if not self._should_keep_pair_as_change(best_pair, diff, left_text, right_text):
                continue

            key = (
                str(best_pair["left"]["row"].get("id") or ""),
                str(best_pair["right"]["row"].get("id") or ""),
                str(diff.get("field_type") or ""),
                str(diff.get("left_raw") or ""),
                str(diff.get("right_raw") or ""),
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            matched_left.add(best_pair["left"]["row"].get("id", ""))
            matched_right.add(best_pair["right"]["row"].get("id", ""))
            changes.append(self._build_change(change_id=len(changes) + 1, pair=best_pair, diff=diff, strategy=strategy))

        for row in left_rows:
            row_id = str(row.get("id") or "")
            if row_id and row_id in matched_left:
                continue
            if str(row.get("row_type") or "block") != "block":
                continue
            if not self._is_meaningful_unmatched(row, right_rows):
                continue
            if len(changes) >= 18:
                break
            changes.append(self._build_unmatched_change(change_id=len(changes) + 1, side="left", row=row))

        for row in right_rows:
            row_id = str(row.get("id") or "")
            if row_id and row_id in matched_right:
                continue
            if str(row.get("row_type") or "block") != "block":
                continue
            if not self._is_meaningful_unmatched(row, left_rows):
                continue
            if len(changes) >= 18:
                break
            changes.append(self._build_unmatched_change(change_id=len(changes) + 1, side="right", row=row))

        changes.sort(
            key=lambda item: (
                -self._importance_rank(item.get("importance")),
                int(item.get("left_page") or item.get("right_page") or 0),
                item.get("title") or "",
            )
        )
        return self._merge_related_changes(changes[:18])

    @staticmethod
    def _should_keep_pair_as_change(
        pair: dict[str, Any],
        diff: dict[str, Any],
        left_text: str,
        right_text: str,
    ) -> bool:
        shared_fields = pair.get("shared_field_types") or []
        reason = str(pair.get("pairing_reason") or "")
        left_section = normalize_text(pair.get("left", {}).get("row", {}).get("section_hint") or "")
        right_section = normalize_text(pair.get("right", {}).get("row", {}).get("section_hint") or "")
        if shared_fields:
            return True
        if "same_section_hint" in reason:
            return True
        if diff.get("field_type") != "block_text":
            return True
        if left_section and right_section and left_section != right_section:
            return False
        similarity = difflib.SequenceMatcher(
            a=normalize_text(left_text),
            b=normalize_text(right_text),
            autojunk=False,
        ).ratio()
        return similarity >= 0.9

    def _candidate_right_rows(self, left_row: dict[str, Any], right_rows: list[dict[str, Any]], index: int) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add(row: dict[str, Any]) -> None:
            row_id = str(row.get("id") or "")
            if row_id and row_id in seen:
                return
            seen.add(row_id)
            candidates.append(row)

        left_section = normalize_text(left_row.get("section_hint") or "")
        left_page = int(left_row.get("page_number") or 0)
        left_fact_types = {fact.get("field_type") for fact in (left_row.get("facts") or [])}
        left_row_type = str(left_row.get("row_type") or "block")

        if left_section:
            for row in right_rows:
                if normalize_text(row.get("section_hint") or "") == left_section:
                    add(row)

        for row in right_rows:
            page = int(row.get("page_number") or 0)
            if left_page and page and abs(page - left_page) <= 1:
                add(row)

        for offset in (0, 1, -1, 2, -2):
            target = index + offset
            if 0 <= target < len(right_rows):
                add(right_rows[target])

        if left_fact_types:
            for row in right_rows:
                right_fact_types = {fact.get("field_type") for fact in (row.get("facts") or [])}
                if left_fact_types & right_fact_types:
                    add(row)

        for row in right_rows:
            if str(row.get("row_type") or "block") == left_row_type:
                add(row)

        return candidates

    def _merge_related_changes(self, changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        for change in changes:
            if not merged or not self._can_merge_changes(merged[-1], change):
                merged.append(change)
                continue
            merged[-1] = self._merge_change_pair(merged[-1], change)
        return merged

    @staticmethod
    def _can_merge_changes(left: dict[str, Any], right: dict[str, Any]) -> bool:
        if left.get("change_type") != "modified" or right.get("change_type") != "modified":
            return False
        if left.get("change_subtype") != right.get("change_subtype"):
            return False
        if left.get("field_type") != "block_text" or right.get("field_type") != "block_text":
            return False
        left_page = int(left.get("left_page") or 0)
        right_page = int(right.get("left_page") or 0)
        if left_page and right_page and abs(left_page - right_page) > 1:
            return False
        left_section = normalize_text(
            str((left.get("left_evidence") or [{}])[0].get("section_hint") or "")
            or str((left.get("right_evidence") or [{}])[0].get("section_hint") or "")
        )
        right_section = normalize_text(
            str((right.get("left_evidence") or [{}])[0].get("section_hint") or "")
            or str((right.get("right_evidence") or [{}])[0].get("section_hint") or "")
        )
        if left_section and right_section and left_section != right_section:
            return False
        return True

    def _merge_change_pair(self, left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
        section_hint = (
            str((left.get("left_evidence") or [{}])[0].get("section_hint") or "")
            or str((right.get("left_evidence") or [{}])[0].get("section_hint") or "")
        ).strip()
        merged_left = "\n".join(item for item in [left.get("left_raw"), right.get("left_raw")] if item)
        merged_right = "\n".join(item for item in [left.get("right_raw"), right.get("right_raw")] if item)
        title = f"Modifications groupées dans {section_hint}" if section_hint else "Modifications groupées"
        return {
            **left,
            "title": title,
            "summary": f"{left.get('summary', '')} {right.get('summary', '')}".strip(),
            "left_raw": merged_left,
            "right_raw": merged_right,
            "lexical_diff_ops": (left.get("lexical_diff_ops") or []) + (right.get("lexical_diff_ops") or []),
            "left_evidence": self._dedupe_rows((left.get("left_evidence") or []) + (right.get("left_evidence") or [])),
            "right_evidence": self._dedupe_rows((left.get("right_evidence") or []) + (right.get("right_evidence") or [])),
            "structured_diffs": (left.get("structured_diffs") or []) + (right.get("structured_diffs") or []),
            "alignment_confidence": min(left.get("alignment_confidence", 0.0), right.get("alignment_confidence", 0.0)),
        }

    @staticmethod
    def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            row_id = str(row.get("id") or "")
            if row_id and row_id in seen:
                continue
            seen.add(row_id)
            output.append(row)
        return output

    @staticmethod
    def _is_meaningful_unmatched(row: dict[str, Any], opposite_rows: list[dict[str, Any]]) -> bool:
        text = str(row.get("text") or "").strip()
        normalized = str(row.get("normalized_text") or normalize_text(text))
        section_hint = normalize_text(row.get("section_hint") or "")
        if len(normalized) < 12:
            return False
        for other in opposite_rows:
            other_text = str(other.get("text") or "").strip()
            other_normalized = str(other.get("normalized_text") or normalize_text(other_text))
            other_section_hint = normalize_text(other.get("section_hint") or "")
            if not other_normalized:
                continue
            if normalized == other_normalized:
                return False
            if section_hint and other_section_hint and section_hint != other_section_hint:
                continue
            if difflib.SequenceMatcher(a=normalized, b=other_normalized, autojunk=False).ratio() >= 0.94:
                return False
        return True

    async def _semantic_alignment_candidates(
        self,
        document: PreparedDocument,
        source_row: dict[str, Any],
        index_name: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        text = str(source_row.get("text") or "").strip()
        if not text:
            return []
        query = re.sub(r"\s+", " ", text)[:180]
        retrieval = await self._retrieve_for_document(
            document=document,
            claim=query,
            strategy="semantic",
            index_name=index_name,
            top_k=top_k,
        )
        return retrieval["evidence"][:top_k]

    @staticmethod
    def _merge_candidate_rows(primary: list[dict[str, Any]], secondary: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in primary + secondary:
            row_id = str(row.get("id") or "")
            if row_id and row_id in seen:
                continue
            seen.add(row_id)
            merged.append(row)
        return merged

    def _build_change(
        self,
        change_id: int,
        pair: dict[str, Any],
        diff: dict[str, Any],
        strategy: str,
    ) -> dict[str, Any]:
        left_row = pair["left"]["row"]
        right_row = pair["right"]["row"]
        subtype = diff.get("change_subtype") or "text_change"
        field_type = diff.get("field_type") or "block_text"
        title = self._change_title(subtype=subtype, field_type=field_type, section_hint=left_row.get("section_hint") or right_row.get("section_hint"))
        summary = self._change_summary(subtype=subtype, diff=diff)
        lexical_diff_ops = diff.get("lexical_diff_ops") or []
        return {
            "change_id": f"change-{change_id}",
            "title": title,
            "summary": summary,
            "change_type": "modified",
            "change_subtype": subtype,
            "importance": self._importance_for_subtype(subtype),
            "field_type": field_type,
            "left_raw": diff.get("left_raw") or left_row.get("text", ""),
            "right_raw": diff.get("right_raw") or right_row.get("text", ""),
            "left_page": int((left_row.get("metadata") or {}).get("page_number") or 0),
            "right_page": int((right_row.get("metadata") or {}).get("page_number") or 0),
            "alignment_source": self._alignment_source_for_strategy(strategy),
            "alignment_confidence": min(1.0, round(float(pair.get("pair_score", 0.0)) / 5.0, 3)),
            "pairing_reason": pair.get("pairing_reason"),
            "structured_diff": diff,
            "structured_diffs": [diff],
            "lexical_diff_ops": lexical_diff_ops,
            "left_evidence": [left_row],
            "right_evidence": [right_row],
            "retrieval": {
                "strategy": strategy,
                "candidate_count": 2,
                "pair_candidate_count": 1,
                "best_pair_reason": pair.get("pairing_reason"),
                "semantic_rerank_count": 1 if strategy in {"semantic", "hybrid"} else 0,
            },
        }

    def _build_unmatched_change(self, change_id: int, side: str, row: dict[str, Any]) -> dict[str, Any]:
        page = int((row.get("metadata") or {}).get("page_number") or 0)
        title = "Bloc ajouté" if side == "right" else "Bloc supprimé"
        summary = "A text block appears only in one document."
        base = {
            "change_id": f"change-{change_id}",
            "title": title,
            "summary": summary,
            "change_type": "added" if side == "right" else "removed",
            "change_subtype": "text_change",
            "importance": "medium",
            "field_type": "block_text",
            "left_raw": row.get("text", "") if side == "left" else "",
            "right_raw": row.get("text", "") if side == "right" else "",
            "left_page": page if side == "left" else 0,
            "right_page": page if side == "right" else 0,
            "alignment_source": "lexical",
            "alignment_confidence": 0.0,
            "pairing_reason": "unmatched_block",
            "structured_diff": {},
            "structured_diffs": [],
            "lexical_diff_ops": [],
            "left_evidence": [row] if side == "left" else [],
            "right_evidence": [row] if side == "right" else [],
            "retrieval": {"strategy": "local", "candidate_count": 1, "pair_candidate_count": 0, "best_pair_reason": "unmatched_block", "semantic_rerank_count": 0},
        }
        return base

    @staticmethod
    def _change_title(subtype: str, field_type: str, section_hint: str | None = None) -> str:
        if subtype == "date_change":
            return "Date modifiée"
        if subtype == "numeric_change":
            return "Valeur numérique modifiée"
        if subtype == "reference_change":
            return "Référence modifiée"
        if section_hint:
            return f"Modification dans {section_hint}"
        if field_type != "block_text":
            return f"{field_type.replace('_', ' ').title()} modifié"
        return "Clause modifiée"

    @staticmethod
    def _change_summary(subtype: str, diff: dict[str, Any]) -> str:
        left_raw = str(diff.get("left_raw") or "").strip()
        right_raw = str(diff.get("right_raw") or "").strip()
        if subtype == "date_change":
            return f"Date changed from '{left_raw}' to '{right_raw}'."
        if subtype == "numeric_change":
            return f"Numeric value changed from '{left_raw}' to '{right_raw}'."
        if subtype == "reference_change":
            return f"Reference changed from '{left_raw}' to '{right_raw}'."
        return "The aligned blocks differ textually between the two documents."

    @staticmethod
    def _importance_for_subtype(subtype: str) -> str:
        if subtype in {"numeric_change", "date_change", "reference_change"}:
            return "high"
        if subtype == "clause_change":
            return "medium"
        return "medium"

    @staticmethod
    def _importance_rank(importance: str | None) -> int:
        return {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(str(importance or "medium"), 2)

    def _group_changes(self, changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for change in changes:
            key = str(change.get("change_subtype") or "text_change")
            counts[key] = counts.get(key, 0) + 1
        return [{"key": key, "count": value} for key, value in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]

    def _summarize_changes(self, changes: list[dict[str, Any]], model: str | None) -> tuple[str, dict[str, Any]]:
        if not changes:
            return "", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        payload = []
        for change in changes[:10]:
            payload.append(
                {
                    "title": change.get("title"),
                    "type": change.get("change_type"),
                    "subtype": change.get("change_subtype"),
                    "importance": change.get("importance"),
                    "left_page": change.get("left_page"),
                    "right_page": change.get("right_page"),
                    "left_raw": str(change.get("left_raw") or "")[:120],
                    "right_raw": str(change.get("right_raw") or "")[:120],
                }
            )
        prompt = (
            "You are a document comparison analyst.\n"
            "Summarize the important differences between two documents.\n"
            "Write 3 short French bullet points max.\n"
            "No intro. No JSON.\n"
            f"CHANGES:\n{json.dumps(payload, ensure_ascii=False)}"
        )
        try:
            response = self.llm_client.analyze_sync(
                prompt=prompt,
                model=model,
                temperature=0.0,
                max_tokens=180,
            )
        except Exception:
            return self._deterministic_summary(changes), {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        content = (response.get("content") or "").strip()
        if not content:
            return self._deterministic_summary(changes), response.get("usage", {}) or {}
        return content, response.get("usage", {}) or {}

    def _deterministic_summary(self, changes: list[dict[str, Any]]) -> str:
        if not changes:
            return "Aucune différence significative détectée."
        top = changes[:3]
        return "\n".join(f"- {item.get('title')}: {item.get('summary')}" for item in top)

    def _change_to_issue(self, change: dict[str, Any], index: int, strategy: str) -> dict[str, Any]:
        return {
            "issue_id": f"issue-{index}",
            "claim": change.get("title") or f"Change {index}",
            "category": change.get("field_type") or "general",
            "business_type": change.get("field_type") or "general",
            "verdict": "inconsistent",
            "severity": change.get("importance") or "medium",
            "confidence": change.get("alignment_confidence", 0.0),
            "summary": change.get("summary") or "",
            "rationale": change.get("summary") or "",
            "decision_source": "diff",
            "alignment_pairs": [
                {
                    "left_block_id": change.get("left_evidence", [{}])[0].get("id") if change.get("left_evidence") else None,
                    "right_block_id": change.get("right_evidence", [{}])[0].get("id") if change.get("right_evidence") else None,
                    "alignment_source": change.get("alignment_source") or strategy,
                    "alignment_score": change.get("alignment_confidence", 0.0),
                    "alignment_confidence": change.get("alignment_confidence", 0.0),
                    "pairing_reason": change.get("pairing_reason"),
                    "lexical_score": 0.0,
                    "semantic_score": 0.0,
                    "business_type": change.get("field_type") or "general",
                    "position_delta": abs(int(change.get("left_page") or 0) - int(change.get("right_page") or 0)),
                }
            ],
            "evidence_quality": "high" if change.get("alignment_confidence", 0.0) >= 0.5 else "medium",
            "ambiguity_reason": None,
            "structured_diffs": change.get("structured_diffs") or [],
            "left_evidence": change.get("left_evidence") or [],
            "right_evidence": change.get("right_evidence") or [],
            "evidence_used_ids": [
                item.get("id")
                for item in (change.get("left_evidence") or []) + (change.get("right_evidence") or [])
                if item.get("id")
            ],
            "suggested": False,
            "usage": {},
            "latency_ms": 0.0,
            "raw_content": "",
            "retrieval": change.get("retrieval") or {},
        }

    @staticmethod
    def _count_changed_tokens(diff_ops: list[dict[str, Any]]) -> int:
        return sum(len(re.findall(r"\S+", item.get("text", ""))) for item in diff_ops if item.get("op") != "equal")

    @staticmethod
    def _alignment_source_for_strategy(strategy: str) -> str:
        if strategy == "semantic":
            return "semantic"
        if strategy in {"lexical", "rg"}:
            return "lexical"
        return "hybrid"

    def _serialize_alignment_pairs(self, pairs: list[dict[str, Any]], strategy: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for pair in pairs:
            left_row = pair["left"]["row"]
            right_row = pair["right"]["row"]
            rows.append(
                {
                    "left_block_id": left_row.get("id"),
                    "right_block_id": right_row.get("id"),
                    "alignment_source": self._alignment_source_for_strategy(strategy),
                    "alignment_score": pair.get("pair_score", 0.0),
                    "alignment_confidence": min(1.0, round(float(pair.get("pair_score", 0.0)) / 5.0, 3)),
                    "pairing_reason": pair.get("pairing_reason"),
                    "lexical_score": round(float(pair["left"].get("base_score", 0.0)) + float(pair["right"].get("base_score", 0.0)), 6),
                    "semantic_score": round(float(pair.get("pair_score", 0.0)) if strategy in {"semantic", "hybrid"} else 0.0, 6),
                    "business_type": pair.get("left", {}).get("facts", [{}])[0].get("category") if pair.get("left", {}).get("facts") else "general",
                    "position_delta": abs(
                        int((left_row.get("metadata") or {}).get("page_number") or 0)
                        - int((right_row.get("metadata") or {}).get("page_number") or 0)
                    ),
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
