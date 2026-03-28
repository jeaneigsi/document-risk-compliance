"""Decision logic for final inconsistency output."""


SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def _type_weight(conflict_type: str) -> int:
    if conflict_type == "amount_conflict":
        return 4
    if conflict_type == "date_conflict":
        return 3
    if conflict_type in {"reference_mismatch", "clause_conflict"}:
        return 2
    return 1


def score_severity(conflicts: list[dict]) -> str:
    """Aggregate conflict evidence into one severity label."""
    if not conflicts:
        return "low"

    max_hint = 1
    weighted = 0
    for conflict in conflicts:
        hint = conflict.get("severity_hint", "low")
        max_hint = max(max_hint, SEVERITY_RANK.get(hint, 1))
        weighted += _type_weight(conflict.get("type", ""))

    if max_hint >= 4 or weighted >= 8:
        return "critical"
    if max_hint >= 3 or weighted >= 5:
        return "high"
    if max_hint >= 2 or weighted >= 2:
        return "medium"
    return "low"


def recommend_action(severity: str) -> str:
    if severity == "critical":
        return "Block publishing and request immediate manual review."
    if severity == "high":
        return "Escalate to reviewer before validation."
    if severity == "medium":
        return "Flag for analyst verification."
    return "No blocking action required."

