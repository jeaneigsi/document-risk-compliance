"""Regex query planning for trigram prefiltering."""

from dataclasses import dataclass
import re
from typing import Any

try:  # Python 3.11+ internal parser modules
    from re import _constants as sre_constants  # type: ignore[attr-defined]
    from re import _parser as sre_parse  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - fallback for older runtimes
    import sre_constants  # type: ignore[no-redef]
    import sre_parse  # type: ignore[no-redef]


_REGEX_META_CHARS = set(".^$*+?{}[]\\|()")
_REGEX_FLAG_MAP = {
    "i": re.IGNORECASE,
    "m": re.MULTILINE,
    "s": re.DOTALL,
    "x": re.VERBOSE,
}


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()


def trigrams(value: str) -> set[str]:
    text = normalize_text(value)
    if len(text) < 3:
        return {text} if text else set()
    return {text[i : i + 3] for i in range(len(text) - 2)}


@dataclass(slots=True)
class RegexQueryPlan:
    is_regex: bool
    pattern: str
    flags: int
    clauses: list[set[str]]


def parse_regex_query(query: str) -> tuple[bool, str, int]:
    raw = query.strip()
    if not raw:
        return False, "", 0

    if raw.startswith("/"):
        slash_idx = -1
        for idx in range(len(raw) - 1, 0, -1):
            if raw[idx] == "/" and raw[idx - 1] != "\\":
                slash_idx = idx
                break
        if slash_idx > 0:
            pattern = raw[1:slash_idx]
            flags_str = raw[slash_idx + 1 :]
            flags = 0
            for flag in flags_str:
                flags |= _REGEX_FLAG_MAP.get(flag.lower(), 0)
            return True, pattern, flags

    if any(ch in _REGEX_META_CHARS for ch in raw):
        return True, raw, 0
    return False, raw, 0


def build_regex_query_plan(
    query: str,
    max_clauses: int = 64,
    max_clause_trigrams: int = 32,
) -> RegexQueryPlan | None:
    is_regex, pattern, flags = parse_regex_query(query)
    if not is_regex:
        return RegexQueryPlan(is_regex=False, pattern=pattern, flags=flags, clauses=[])

    try:
        parsed = sre_parse.parse(pattern, flags)
    except re.error:
        return None

    clauses = _subpattern_clauses(
        parsed,
        max_clauses=max_clauses,
        max_clause_trigrams=max_clause_trigrams,
    )
    return RegexQueryPlan(is_regex=True, pattern=pattern, flags=flags, clauses=clauses)


def _flush_tail(required: set[str], literal_tail: str, max_clause_trigrams: int) -> tuple[set[str], str]:
    if literal_tail:
        required = set(required)
        required.update(trigrams(literal_tail))
        if len(required) > max_clause_trigrams:
            # Keep a stable subset; fewer terms still preserves correctness of final regex verification.
            required = set(sorted(required)[:max_clause_trigrams])
    return required, ""


def _dedupe_clauses(clauses: list[set[str]], max_clauses: int) -> list[set[str]]:
    seen: set[tuple[str, ...]] = set()
    out: list[set[str]] = []
    for clause in clauses:
        key = tuple(sorted(clause))
        if key in seen:
            continue
        seen.add(key)
        out.append(clause)
        if len(out) >= max_clauses:
            break
    return out


def _subpattern_clauses(
    subpattern: Any,
    max_clauses: int,
    max_clause_trigrams: int,
) -> list[set[str]]:
    states: list[tuple[set[str], str]] = [(set(), "")]

    for op, arg in subpattern.data:
        if op == sre_constants.LITERAL:
            ch = chr(arg)
            states = [(required, tail + ch) for required, tail in states]
            continue

        if op == sre_constants.SUBPATTERN:
            _, _, _, nested = arg
            nested_clauses = _subpattern_clauses(
                nested,
                max_clauses=max_clauses,
                max_clause_trigrams=max_clause_trigrams,
            )
            next_states: list[tuple[set[str], str]] = []
            for required, tail in states:
                flushed_required, _ = _flush_tail(required, tail, max_clause_trigrams)
                for clause in nested_clauses or [set()]:
                    merged = set(flushed_required)
                    merged.update(clause)
                    next_states.append((merged, ""))
            states = next_states or states
            states = _dedupe_state(states, max_clauses=max_clauses)
            continue

        if op == sre_constants.BRANCH:
            _, branches = arg
            branch_clauses: list[set[str]] = []
            for branch in branches:
                branch_clauses.extend(
                    _subpattern_clauses(
                        branch,
                        max_clauses=max_clauses,
                        max_clause_trigrams=max_clause_trigrams,
                    )
                )
            branch_clauses = _dedupe_clauses(branch_clauses, max_clauses=max_clauses)
            next_states: list[tuple[set[str], str]] = []
            for required, tail in states:
                flushed_required, _ = _flush_tail(required, tail, max_clause_trigrams)
                for clause in branch_clauses or [set()]:
                    merged = set(flushed_required)
                    merged.update(clause)
                    next_states.append((merged, ""))
            states = _dedupe_state(next_states or states, max_clauses=max_clauses)
            continue

        if op in (sre_constants.MAX_REPEAT, sre_constants.MIN_REPEAT):
            min_repeat, _, nested = arg
            if min_repeat <= 0:
                # Optional part: no mandatory trigram constraints.
                states = [
                    _flush_tail(required, tail, max_clause_trigrams)
                    for required, tail in states
                ]
                continue
            nested_clauses = _subpattern_clauses(
                nested,
                max_clauses=max_clauses,
                max_clause_trigrams=max_clause_trigrams,
            )
            next_states = []
            for required, tail in states:
                flushed_required, _ = _flush_tail(required, tail, max_clause_trigrams)
                for clause in nested_clauses or [set()]:
                    merged = set(flushed_required)
                    merged.update(clause)
                    next_states.append((merged, ""))
            states = _dedupe_state(next_states or states, max_clauses=max_clauses)
            continue

        # Any non-literal construct breaks contiguous literals.
        states = [
            _flush_tail(required, tail, max_clause_trigrams)
            for required, tail in states
        ]

    finalized = [
        _flush_tail(required, tail, max_clause_trigrams)[0]
        for required, tail in states
    ]
    return _dedupe_clauses(finalized, max_clauses=max_clauses)


def _dedupe_state(
    states: list[tuple[set[str], str]],
    max_clauses: int,
) -> list[tuple[set[str], str]]:
    seen: set[tuple[tuple[str, ...], str]] = set()
    out: list[tuple[set[str], str]] = []
    for required, tail in states:
        key = (tuple(sorted(required)), tail)
        if key in seen:
            continue
        seen.add(key)
        out.append((required, tail))
        if len(out) >= max_clauses:
            break
    return out
