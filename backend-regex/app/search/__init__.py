"""Search module - Phase 3.

Ce module contiendra :
- Client NextPlaid
- Recherche hybride (vectorielle + keyword)
- Reranking
"""

from app.search.evidence import (
    EvidenceUnit,
    build_evidence_units_from_ocr,
    map_find_to_evidence_units,
)
from app.search.embedding_client import EmbeddingClient
from app.search.cursor_like import CursorLikeIndex, InvertedIndex, TrigramIndex
from app.search.local_registry import LocalSearchRegistry, get_local_search_registry
from app.search.metrics import mrr, ndcg_at_k, recall_at_k
from app.search.nextplaid_client import NextPlaidClient
from app.search.pipeline import SearchPipeline
from app.search.regex_planner import RegexQueryPlan, build_regex_query_plan, parse_regex_query
from app.search.ranking import fuse_search_results, rank_search_results

__all__ = [
    "EvidenceUnit",
    "build_evidence_units_from_ocr",
    "map_find_to_evidence_units",
    "EmbeddingClient",
    "TrigramIndex",
    "InvertedIndex",
    "CursorLikeIndex",
    "LocalSearchRegistry",
    "get_local_search_registry",
    "NextPlaidClient",
    "SearchPipeline",
    "RegexQueryPlan",
    "parse_regex_query",
    "build_regex_query_plan",
    "rank_search_results",
    "fuse_search_results",
    "recall_at_k",
    "mrr",
    "ndcg_at_k",
]
