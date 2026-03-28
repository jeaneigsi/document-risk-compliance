"""Minimal context compression for detection explanations."""

from pydantic import BaseModel, Field


class MinimalContextBundle(BaseModel):
    """Smallest evidence package passed to decision/LLM layers."""

    claim: str
    snippets: list[str] = Field(default_factory=list)
    max_chars: int = 1200

    @property
    def text(self) -> str:
        content = "\n---\n".join([self.claim, *self.snippets]).strip()
        if len(content) <= self.max_chars:
            return content
        return content[: self.max_chars].rstrip() + "..."

    @property
    def compression_ratio(self) -> float:
        raw = len(self.claim) + sum(len(s) for s in self.snippets)
        if raw == 0:
            return 1.0
        return len(self.text) / raw


def build_minimal_context(
    claim: str,
    evidence_snippets: list[str],
    max_chars: int = 1200,
) -> MinimalContextBundle:
    """Pick shortest useful snippets until max size."""
    snippets: list[str] = []
    remaining = max_chars - len(claim)
    for snippet in evidence_snippets:
        cleaned = snippet.strip()
        if not cleaned:
            continue
        if remaining <= 0:
            break
        if len(cleaned) + 5 <= remaining:
            snippets.append(cleaned)
            remaining -= len(cleaned) + 5
        else:
            snippets.append(cleaned[: max(0, remaining - 3)] + "...")
            break
    return MinimalContextBundle(claim=claim, snippets=snippets, max_chars=max_chars)

