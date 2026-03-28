"""Data models used by the evaluation framework (Phase 7)."""

from dataclasses import dataclass, field


@dataclass(slots=True)
class SearchEvalSample:
    """Ground-truth sample for retrieval evaluation."""

    sample_id: str
    query: str
    relevant_ids: set[str]
    relevance_by_id: dict[str, float] = field(default_factory=dict)
    index_name: str = "default"
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class DetectionEvalSample:
    """Ground-truth sample for binary inconsistency detection."""

    sample_id: str
    gold_conflict: bool
    predicted_conflict: bool
    conflict_type: str = "generic"


@dataclass(slots=True)
class EconomicSample:
    """Runtime/cost record for one evaluated run."""

    sample_id: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    compression_ratio: float = 1.0
    llm_calls: int = 0
