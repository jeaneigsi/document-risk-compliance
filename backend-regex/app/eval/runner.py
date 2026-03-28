"""Evaluation runner for search/detection/economic metrics."""

import logging
from time import perf_counter

from app.eval.datasets import load_find_eval_pack, load_wikipedia_contradict_eval_pack
from app.eval.baseline import BaselineLexicalRetriever
from app.eval.metrics import (
    mrr,
    ndcg_at_k,
    precision_recall_f1,
    recall_at_k,
    summarize_economic_metrics,
)
from app.eval.models import SearchEvalSample
from app.search.evidence import EvidenceUnit
from app.search.pipeline import SearchPipeline

logger = logging.getLogger(__name__)


class EvaluationRunner:
    """Runs comparable evaluation protocols for Phase 7."""

    def __init__(
        self,
        search_pipeline: SearchPipeline | None = None,
        baseline_retriever: BaselineLexicalRetriever | None = None,
    ):
        self.search_pipeline = search_pipeline or SearchPipeline()
        self.baseline_retriever = baseline_retriever or BaselineLexicalRetriever()

    async def evaluate_search(
        self,
        samples: list[SearchEvalSample],
        corpus: list[dict],
        strategy: str = "baseline",
        top_k: int = 10,
    ) -> dict:
        rows: list[dict] = []
        corpus_by_id = {str(item.get("id")): item for item in corpus if item.get("id")}

        for sample in samples:
            sample_error: str | None = None
            semantic_top_k_internal = top_k
            if strategy == "baseline":
                baseline_start = perf_counter()
                results = self.baseline_retriever.search(sample.query, corpus=corpus, top_k=top_k)
                latency_ms = round((perf_counter() - baseline_start) * 1000.0, 3)
                candidate_count = len(corpus)
            else:
                try:
                    run = await self.search_pipeline.run(
                        query=sample.query,
                        index_name=sample.index_name,
                        top_k=top_k,
                        strategy=strategy,
                    )
                    results = run["results"]
                    latency_ms = float(run.get("latency_ms", 0.0))
                    candidate_count = int(run.get("candidate_count", len(results)))
                    sample_error = run.get("semantic_error")
                    semantic_top_k_internal = int(run.get("semantic_top_k_internal", top_k))
                except Exception as exc:
                    results = []
                    latency_ms = 0.0
                    candidate_count = 0
                    sample_error = str(exc)

            retrieved_ids = [str(item.get("id", "")) for item in results if item.get("id")]
            retrieved_items = []
            for rank, item in enumerate(results, start=1):
                item_id = str(item.get("id", ""))
                corpus_item = corpus_by_id.get(item_id, {})
                metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
                corpus_metadata = corpus_item.get("metadata") if isinstance(corpus_item.get("metadata"), dict) else {}
                merged_metadata = {**corpus_metadata, **metadata}
                retrieved_items.append(
                    {
                        "rank": rank,
                        "id": item_id,
                        "score": float(item.get("score", 0.0)),
                        "text": str(item.get("text") or corpus_item.get("text") or ""),
                        "metadata": merged_metadata,
                        "is_relevant": item_id in sample.relevant_ids,
                    }
                )

            relevance_map = sample.relevance_by_id or {rel_id: 1.0 for rel_id in sample.relevant_ids}
            best_relevant_rank = next(
                (rank for rank, item_id in enumerate(retrieved_ids, start=1) if item_id in sample.relevant_ids),
                None,
            )
            gold_present = best_relevant_rank is not None
            relevant_items = []
            for relevant_id in sorted(sample.relevant_ids):
                corpus_item = corpus_by_id.get(relevant_id, {})
                relevant_items.append(
                    {
                        "id": relevant_id,
                        "relevance": float(relevance_map.get(relevant_id, 1.0)),
                        "text": str(corpus_item.get("text") or ""),
                        "metadata": corpus_item.get("metadata") if isinstance(corpus_item.get("metadata"), dict) else {},
                    }
                )

            ndcg_value = ndcg_at_k(relevance_map, retrieved_ids, k=top_k)
            if ndcg_value > 1.0:
                logger.warning(
                    "eval.metric.ndcg_out_of_bounds strategy=%s sample_id=%s ndcg=%s",
                    strategy,
                    sample.sample_id,
                    ndcg_value,
                )

            logger.info(
                "eval.sample strategy=%s sample_id=%s query_len=%s latency_ms=%.3f candidates=%s retrieved=%s gold_present=%s best_relevant_rank=%s error=%s",
                strategy,
                sample.sample_id,
                len(sample.query),
                latency_ms,
                candidate_count,
                len(retrieved_ids),
                gold_present,
                best_relevant_rank,
                sample_error,
            )

            rows.append(
                {
                    "sample_id": sample.sample_id,
                    "query": sample.query,
                    "sample_metadata": sample.metadata,
                    "strategy": strategy,
                    "recall_at_k": recall_at_k(sample.relevant_ids, retrieved_ids, k=top_k),
                    "mrr": mrr(sample.relevant_ids, retrieved_ids),
                    "ndcg_at_k": ndcg_value,
                    "latency_ms": latency_ms,
                    "candidate_count": candidate_count,
                    "candidate_kept_count": len(retrieved_ids),
                    "retrieved_ids": retrieved_ids,
                    "retrieved_items": retrieved_items,
                    "relevant_ids": sorted(sample.relevant_ids),
                    "relevant_items": relevant_items,
                    "gold_present": gold_present,
                    "best_relevant_rank": best_relevant_rank,
                    "semantic_top_k_internal": semantic_top_k_internal,
                    "error": sample_error,
                }
            )

        if not rows:
            return {
                "strategy": strategy,
                "top_k": top_k,
                "samples": 0,
                "mean_recall_at_k": 0.0,
                "mean_mrr": 0.0,
                "mean_ndcg_at_k": 0.0,
                "mean_latency_ms": 0.0,
                "mean_candidate_count": 0.0,
                "mean_candidate_kept_count": 0.0,
                "rows": [],
            }

        count = float(len(rows))
        return {
            "strategy": strategy,
            "top_k": top_k,
            "samples": int(count),
            "mean_recall_at_k": sum(r["recall_at_k"] for r in rows) / count,
            "mean_mrr": sum(r["mrr"] for r in rows) / count,
            "mean_ndcg_at_k": sum(r["ndcg_at_k"] for r in rows) / count,
            "mean_latency_ms": sum(r["latency_ms"] for r in rows) / count,
            "mean_candidate_count": sum(r["candidate_count"] for r in rows) / count,
            "mean_candidate_kept_count": sum(r["candidate_kept_count"] for r in rows) / count,
            "rows": rows,
        }

    def evaluate_detection(self, gold_labels: list[bool], predicted_labels: list[bool]) -> dict:
        return precision_recall_f1(gold_labels, predicted_labels)

    def evaluate_economics(self, runs: list[dict]) -> dict:
        return summarize_economic_metrics(runs)

    async def _index_experiment_corpus(self, corpus: list[dict], index_name: str) -> int:
        """Index experiment corpus so non-baseline strategies run on the same data."""
        evidence_units: list[EvidenceUnit] = []
        for i, row in enumerate(corpus):
            doc_id = str(row.get("id") or f"find-doc-{i}")
            content = str(row.get("text") or "").strip()
            if not content:
                continue
            evidence_units.append(
                EvidenceUnit(
                    evidence_id=doc_id,
                    document_id=doc_id,
                    content=content,
                    source_type="find",
                    page_number=1,
                    metadata=row.get("metadata") or {},
                )
            )

        if not evidence_units:
            return 0

        await self.search_pipeline.index_evidence_units(
            evidence_units=evidence_units,
            index_name=index_name,
        )
        return len(evidence_units)

    async def evaluate_search_strategies(
        self,
        samples: list[SearchEvalSample],
        corpus: list[dict],
        strategies: list[str] | None = None,
        top_k: int = 10,
    ) -> dict:
        """Compare multiple retrieval strategies on the same evaluation pack."""
        selected = strategies or ["baseline", "lexical", "semantic", "hybrid", "rg"]
        reports: dict[str, dict] = {}
        for strategy in selected:
            reports[strategy] = await self.evaluate_search(
                samples=samples,
                corpus=corpus,
                strategy=strategy,
                top_k=top_k,
            )

        best_strategy = max(
            reports.items(),
            key=lambda item: float(item[1].get("mean_recall_at_k", 0.0)),
        )[0] if reports else None

        return {
            "strategies": selected,
            "top_k": top_k,
            "reports": reports,
            "best_strategy_by_recall": best_strategy,
        }

    async def run_find_experiment(
        self,
        dataset_name: str = "kensho/FIND",
        split: str = "validation",
        max_samples: int = 100,
        index_name: str = "default",
        top_k: int = 10,
        strategies: list[str] | None = None,
        streaming: bool = True,
        cache_dir: str | None = None,
        max_query_chars: int = 8192,
    ) -> dict:
        """Phase-8 helper: run multi-strategy comparison on configured benchmark subset."""
        if dataset_name == "kensho/FIND":
            pack = load_find_eval_pack(
                split=split,
                max_samples=max_samples,
                index_name=index_name,
                streaming=streaming,
                cache_dir=cache_dir,
                max_query_chars=max_query_chars,
            )
        elif dataset_name == "ibm-research/Wikipedia_contradict_benchmark":
            pack = load_wikipedia_contradict_eval_pack(
                split=split or "train",
                max_samples=max_samples,
                index_name=index_name,
                cache_dir=cache_dir,
            )
        else:
            raise ValueError(f"Unsupported dataset_name: {dataset_name}")
        selected = strategies or ["baseline", "lexical", "semantic", "hybrid", "rg"]
        needs_index = any(strategy != "baseline" for strategy in selected)
        if needs_index:
            await self._index_experiment_corpus(
                corpus=pack["corpus"],
                index_name=index_name,
            )
        comparison = await self.evaluate_search_strategies(
            samples=pack["samples"],
            corpus=pack["corpus"],
            strategies=selected,
            top_k=top_k,
        )
        return {
            "dataset_name": pack["dataset_name"],
            "split": pack["split"],
            "samples_count": pack["samples_count"],
            "corpus_count": pack["corpus_count"],
            "skipped_too_long_queries": pack.get("skipped_too_long_queries", 0),
            "max_query_chars": pack.get("max_query_chars", max_query_chars),
            "comparison": comparison,
        }
