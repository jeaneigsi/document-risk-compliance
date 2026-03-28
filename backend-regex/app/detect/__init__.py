"""Detection module (Phase 4)."""

from app.detect.comparators import ClauseComparator, SectionComparator, TableComparator
from app.detect.compression import MinimalContextBundle, build_minimal_context
from app.detect.decision import recommend_action, score_severity
from app.detect.deterministic import (
    AmountConflictDetector,
    DateConflictDetector,
    ReferenceMismatchDetector,
)
from app.detect.pipeline import DetectionPipeline

__all__ = [
    "DateConflictDetector",
    "AmountConflictDetector",
    "ReferenceMismatchDetector",
    "ClauseComparator",
    "TableComparator",
    "SectionComparator",
    "MinimalContextBundle",
    "build_minimal_context",
    "score_severity",
    "recommend_action",
    "DetectionPipeline",
]
