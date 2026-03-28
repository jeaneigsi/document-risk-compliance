"""Detection pipeline orchestration."""

import re
from time import perf_counter

from app.detect.comparators import ClauseComparator, SectionComparator, TableComparator
from app.detect.compression import build_minimal_context
from app.detect.decision import recommend_action, score_severity
from app.detect.deterministic import (
    AMOUNT_RE,
    AmountConflictDetector,
    DateConflictDetector,
    ReferenceMismatchDetector,
)
from app.llm import LiteLLMClient, build_detection_prompt
from app.monitor import get_langfuse_tracker, start_span


class DetectionPipeline:
    """Run deterministic + comparator cascade, then compress and decide."""

    def __init__(self, llm_client: LiteLLMClient | None = None):
        self.date_detector = DateConflictDetector()
        self.amount_detector = AmountConflictDetector()
        self.reference_detector = ReferenceMismatchDetector()
        self.clause_comparator = ClauseComparator()
        self.table_comparator = TableComparator()
        self.section_comparator = SectionComparator()
        self.llm_client = llm_client or LiteLLMClient()
        self.tracker = get_langfuse_tracker()

    def run(
        self,
        document_id: str,
        claims: list[str],
        markdown: str,
        layout: list | None = None,
    ) -> dict:
        start = perf_counter()
        with start_span(
            "detect.pipeline.run",
            {"document_id": document_id, "claims_count": len(claims)},
        ):
            snippets = [part.strip() for part in re.split(r"\n\s*\n", markdown) if part.strip()]
            if not snippets and markdown.strip():
                snippets = [markdown.strip()]
            evidence_text = "\n".join(snippets[:8])

            claim_results: list[dict] = []
            all_conflicts: list[dict] = []
            llm_calls_count = 0
            total_prompt_tokens = 0
            total_completion_tokens = 0
            total_llm_cost_usd = 0.0

            for claim in claims:
                conflicts = []
                conflicts.extend(self.date_detector.detect(claim, evidence_text))
                conflicts.extend(self.amount_detector.detect(claim, evidence_text))
                conflicts.extend(self.reference_detector.detect(claim, evidence_text))

                clause_cmp = self.clause_comparator.compare(claim, evidence_text)
                if clause_cmp["conflict"]:
                    conflicts.append({"type": "clause_conflict", "severity_hint": "medium", **clause_cmp})

                claim_numbers = [m.group(1) for m in AMOUNT_RE.finditer(claim)]
                evidence_numbers = [m.group(1) for m in AMOUNT_RE.finditer(evidence_text)]
                table_cmp = self.table_comparator.compare(claim_numbers, evidence_numbers)
                if table_cmp["conflict"]:
                    conflicts.append({"type": "table_conflict", "severity_hint": "high", **table_cmp})

                section_cmp = self.section_comparator.compare(claim, snippets[0] if snippets else evidence_text)
                context = build_minimal_context(claim, snippets[:3], max_chars=1000)
                severity = score_severity(conflicts)

                llm_analysis = None
                if severity in {"high", "critical"}:
                    try:
                        prompt = build_detection_prompt(claim=claim, context=context.text, conflicts=conflicts)
                        llm_analysis = self.llm_client.analyze_sync(prompt)
                        usage = llm_analysis.get("usage", {}) if isinstance(llm_analysis, dict) else {}
                        llm_calls_count += 1
                        total_prompt_tokens += int(usage.get("prompt_tokens", 0))
                        total_completion_tokens += int(usage.get("completion_tokens", 0))
                        total_llm_cost_usd += LiteLLMClient.estimate_cost(
                            usage=usage,
                            input_price_per_1k=getattr(self.llm_client, "input_price_per_1k", 0.0),
                            output_price_per_1k=getattr(self.llm_client, "output_price_per_1k", 0.0),
                        )
                    except Exception as exc:  # pragma: no cover - covered via fallback tests
                        llm_analysis = {
                            "status": "fallback",
                            "reason": str(exc),
                        }

                claim_result = {
                    "claim": claim,
                    "conflicts": conflicts,
                    "severity": severity,
                    "context": context.text,
                    "compression_ratio": round(context.compression_ratio, 4),
                    "llm_analysis": llm_analysis,
                    "comparators": {
                        "clause": clause_cmp,
                        "table": table_cmp,
                        "section": section_cmp,
                    },
                }
                claim_results.append(claim_result)
                all_conflicts.extend(conflicts)

            global_severity = score_severity(all_conflicts)
            latency_ms = round((perf_counter() - start) * 1000.0, 3)
            avg_compression_ratio = (
                sum(float(item["compression_ratio"]) for item in claim_results) / len(claim_results)
                if claim_results
                else 1.0
            )
            trace_id = self.tracker.trace(
                name="detect.run",
                input_payload={"document_id": document_id, "claims": claims},
                metadata={
                    "conflict_count": len(all_conflicts),
                    "severity": global_severity,
                    "latency_ms": latency_ms,
                    "llm_calls_count": llm_calls_count,
                    "prompt_tokens": total_prompt_tokens,
                    "completion_tokens": total_completion_tokens,
                    "avg_compression_ratio": avg_compression_ratio,
                },
            )
            self.tracker.event(
                trace_id=trace_id,
                name="detect.result",
                output={
                    "severity": global_severity,
                    "conflict_count": len(all_conflicts),
                    "latency_ms": latency_ms,
                    "cost_usd": round(total_llm_cost_usd, 8),
                },
            )

            return {
                "status": "completed",
                "document_id": document_id,
                "claims_count": len(claims),
                "conflict_count": len(all_conflicts),
                "severity": global_severity,
                "recommendation": recommend_action(global_severity),
                "results": claim_results,
                "llm_required": global_severity in {"high", "critical"},
                "latency_ms": latency_ms,
                "economics": {
                    "llm_calls_count": llm_calls_count,
                    "prompt_tokens": total_prompt_tokens,
                    "completion_tokens": total_completion_tokens,
                    "total_tokens": total_prompt_tokens + total_completion_tokens,
                    "cost_usd": round(total_llm_cost_usd, 8),
                    "avg_compression_ratio": round(avg_compression_ratio, 4),
                },
                "trace_id": trace_id,
            }
