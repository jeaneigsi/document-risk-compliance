"""Baseline retrieval implementation without Cursor-like/NextPlaid."""

import re


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()


def _tokenize(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", _normalize(value)))


class BaselineLexicalRetriever:
    """Simple lexical baseline based on token overlap + phrase bonus."""

    def search(self, query: str, corpus: list[dict], top_k: int = 10) -> list[dict]:
        q_norm = _normalize(query)
        q_tokens = _tokenize(query)
        if not q_norm:
            return []

        results: list[dict] = []
        for row in corpus:
            row_id = str(row.get("id", ""))
            text = str(row.get("text", ""))
            if not row_id or not text:
                continue

            d_norm = _normalize(text)
            d_tokens = _tokenize(text)

            token_overlap = (len(q_tokens & d_tokens) / len(q_tokens)) if q_tokens else 0.0
            phrase_bonus = 1.0 if q_norm in d_norm else 0.0
            score = (0.8 * token_overlap) + (0.2 * phrase_bonus)
            if score == 0.0:
                continue

            results.append(
                {
                    "id": row_id,
                    "score": round(score, 6),
                    "text": text,
                    "metadata": dict(row.get("metadata", {})),
                    "source": "baseline",
                }
            )

        results.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
        return results[:top_k]
