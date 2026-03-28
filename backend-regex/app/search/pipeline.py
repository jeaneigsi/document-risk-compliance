"""Search pipeline orchestration (Phase 3)."""

import logging
from time import perf_counter

from app.search.evidence import EvidenceUnit
from app.search.local_registry import LocalSearchRegistry, get_local_search_registry
from app.monitor import get_langfuse_tracker, start_span
from app.search.nextplaid_client import NextPlaidClient
from app.search.ranking import fuse_search_results, rank_search_results

logger = logging.getLogger(__name__)


class SearchPipeline:
    """Orchestrates retrieval with NextPlaid and ranking."""

    def __init__(
        self,
        client: NextPlaidClient | None = None,
        registry: LocalSearchRegistry | None = None,
    ):
        self.client = client or NextPlaidClient()
        self.registry = registry or get_local_search_registry()
        self.tracker = get_langfuse_tracker()

    async def run(
        self,
        query: str,
        index_name: str = "default",
        top_k: int = 10,
        strategy: str = "hybrid",
    ) -> dict:
        """Execute search and return ranked results."""
        start = perf_counter()
        with start_span(
            "search.pipeline.run",
            {
                "index_name": index_name,
                "strategy": strategy,
                "top_k": top_k,
            },
        ):
            strategy = strategy.lower()
            semantic_results: list[dict] = []
            lexical_results: list[dict] = []
            semantic_candidate_count = 0
            lexical_candidate_count = 0
            semantic_error: str | None = None
            semantic_top_k_internal = max(top_k, min(50, top_k * 3))

            if strategy in ("semantic", "hybrid"):
                try:
                    semantic_results = await self.client.search(
                        query=query,
                        index_name=index_name,
                        top_k=semantic_top_k_internal if strategy == "hybrid" else top_k,
                    )
                    semantic_candidate_count = len(semantic_results)
                    semantic_results = rank_search_results(
                        semantic_results,
                        top_k=semantic_top_k_internal if strategy == "hybrid" else top_k,
                    )
                except Exception as exc:
                    semantic_error = str(exc)
                    semantic_results = []
                    semantic_candidate_count = 0
                    logger.warning(
                        "semantic search failed index=%s strategy=%s query_len=%s error=%s",
                        index_name,
                        strategy,
                        len(query),
                        exc,
                    )

            if strategy in ("lexical", "hybrid"):
                lexical_results = self.registry.lexical_search(
                    index_name=index_name,
                    query=query,
                    top_k=top_k,
                )
                lexical_candidate_count = len(lexical_results)

            if strategy == "rg":
                lexical_results = self.registry.rg_search(
                    index_name=index_name,
                    query=query,
                    top_k=top_k,
                )
                lexical_candidate_count = len(lexical_results)

            if strategy == "semantic":
                ranked_results = semantic_results
            elif strategy == "lexical":
                ranked_results = lexical_results
            elif strategy == "rg":
                ranked_results = lexical_results
            else:
                ranked_results = fuse_search_results(
                    semantic_results=semantic_results,
                    lexical_results=lexical_results,
                    top_k=top_k,
                )

            if strategy == "semantic":
                candidate_count = semantic_candidate_count
            elif strategy in ("lexical", "rg"):
                candidate_count = lexical_candidate_count
            else:
                unique_ids = {
                    str(item.get("id"))
                    for item in (semantic_results + lexical_results)
                    if item.get("id")
                }
                candidate_count = len(unique_ids)
            candidate_kept_count = len(ranked_results)
            latency_ms = round((perf_counter() - start) * 1000.0, 3)

            trace_id = self.tracker.trace(
                name="search.run",
                input_payload={"query": query, "index_name": index_name, "strategy": strategy},
                metadata={
                    "top_k": top_k,
                    "latency_ms": latency_ms,
                    "candidate_count": candidate_count,
                    "candidate_kept_count": candidate_kept_count,
                    "semantic_top_k_internal": semantic_top_k_internal if strategy == "hybrid" else top_k,
                },
            )
            self.tracker.event(
                trace_id=trace_id,
                name="search.results",
                output={"count": len(ranked_results)},
                metadata={
                    "strategy": strategy,
                    "latency_ms": latency_ms,
                    "candidate_count": candidate_count,
                    "candidate_kept_count": candidate_kept_count,
                    "semantic_top_k_internal": semantic_top_k_internal if strategy == "hybrid" else top_k,
                },
            )

            return {
                "status": "completed",
                "query": query,
                "index_name": index_name,
                "strategy": strategy,
                "count": len(ranked_results),
                "results": ranked_results,
                "latency_ms": latency_ms,
                "candidate_count": candidate_count,
                "candidate_kept_count": candidate_kept_count,
                "trace_id": trace_id,
                "semantic_error": semantic_error,
                "semantic_top_k_internal": semantic_top_k_internal if strategy == "hybrid" else top_k,
            }

    async def index_evidence_units(
        self,
        evidence_units: list[EvidenceUnit],
        index_name: str = "default",
    ) -> dict:
        """Push evidence units to NextPlaid index."""
        with start_span(
            "search.pipeline.index",
            {"index_name": index_name, "items": len(evidence_units)},
        ):
            if not evidence_units:
                return {"status": "completed", "index_name": index_name, "indexed_count": 0}

            local_count = self.registry.add_evidence_units(index_name=index_name, evidence_units=evidence_units)
            response = await self.client.index_evidence_units(
                evidence_units=evidence_units,
                index_name=index_name,
            )

            trace_id = self.tracker.trace(
                name="search.index",
                input_payload={"index_name": index_name, "items": len(evidence_units)},
                metadata={"local_indexed_count": local_count},
            )
            self.tracker.event(trace_id=trace_id, name="search.indexed", output=response)

            return {
                "status": "completed",
                "index_name": index_name,
                "indexed_count": len(evidence_units),
                "local_indexed_count": local_count,
                "provider_response": response,
                "trace_id": trace_id,
            }
