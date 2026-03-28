"""Cursor-like lexical indexing: trigram + inverted index."""

import re
from collections import Counter, defaultdict

from app.search.regex_planner import build_regex_query_plan


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()


def _tokenize(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", _normalize_text(value))


def _trigrams(value: str) -> set[str]:
    text = _normalize_text(value)
    if len(text) < 3:
        return {text} if text else set()
    return {text[i : i + 3] for i in range(len(text) - 2)}


class TrigramIndex:
    """Trigram postings index."""

    def __init__(self):
        self.postings: dict[str, set[str]] = defaultdict(set)
        self.doc_trigrams: dict[str, set[str]] = {}
        self.doc_ids: set[str] = set()

    def add(self, doc_id: str, text: str) -> None:
        trigs = _trigrams(text)
        self.doc_trigrams[doc_id] = trigs
        self.doc_ids.add(doc_id)
        for trig in trigs:
            self.postings[trig].add(doc_id)

    def candidates(self, query: str) -> set[str]:
        q_trigs = _trigrams(query)
        if not q_trigs:
            return set()
        candidates: set[str] | None = None
        for trig in q_trigs:
            docs = self.postings.get(trig, set())
            if candidates is None:
                candidates = set(docs)
            else:
                candidates &= docs
            if not candidates:
                break
        return candidates if candidates is not None else set()

    def candidates_for_all_trigrams(self, trigrams: set[str]) -> set[str]:
        if not trigrams:
            return set()
        candidates: set[str] | None = None
        for trig in trigrams:
            docs = self.postings.get(trig, set())
            if candidates is None:
                candidates = set(docs)
            else:
                candidates &= docs
            if not candidates:
                break
        return candidates if candidates is not None else set()

    def candidates_from_clauses(self, clauses: list[set[str]]) -> set[str]:
        if not clauses:
            return set()
        union_docs: set[str] = set()
        for clause in clauses:
            if not clause:
                union_docs |= self.doc_ids
                continue
            union_docs |= self.candidates_for_all_trigrams(clause)
        return union_docs

    def overlap_ratio(self, doc_id: str, query: str) -> float:
        q_trigs = _trigrams(query)
        d_trigs = self.doc_trigrams.get(doc_id, set())
        if not q_trigs or not d_trigs:
            return 0.0
        return len(q_trigs & d_trigs) / len(q_trigs)


class InvertedIndex:
    """Token inverted index."""

    def __init__(self):
        self.postings: dict[str, set[str]] = defaultdict(set)
        self.doc_tf: dict[str, Counter[str]] = {}

    def add(self, doc_id: str, text: str) -> None:
        tokens = _tokenize(text)
        tf = Counter(tokens)
        self.doc_tf[doc_id] = tf
        for token in tf:
            self.postings[token].add(doc_id)

    def candidates(self, query: str) -> set[str]:
        q_tokens = _tokenize(query)
        if not q_tokens:
            return set()
        docs: set[str] = set()
        for token in q_tokens:
            docs |= self.postings.get(token, set())
        return docs

    def token_score(self, doc_id: str, query: str) -> float:
        tf = self.doc_tf.get(doc_id, Counter())
        q_tokens = _tokenize(query)
        if not q_tokens:
            return 0.0
        matches = sum(1 for t in q_tokens if tf.get(t, 0) > 0)
        return matches / len(q_tokens)


class CursorLikeIndex:
    """Hybrid lexical index inspired by cursor-like regex prefiltering."""

    def __init__(self):
        self.trigram = TrigramIndex()
        self.inverted = InvertedIndex()
        self.documents: dict[str, dict] = {}

    def add_documents(self, documents: list[dict]) -> None:
        for doc in documents:
            doc_id = str(doc["id"])
            text = str(doc.get("text", ""))
            metadata = dict(doc.get("metadata", {}))
            self.documents[doc_id] = {"id": doc_id, "text": text, "metadata": metadata}
            self.trigram.add(doc_id, text)
            self.inverted.add(doc_id, text)

    def search(self, query: str, top_k: int = 10) -> list[dict]:
        if not query.strip():
            return []

        plan = build_regex_query_plan(query)
        if plan and plan.is_regex:
            regex_results = self._search_regex(
                pattern=plan.pattern,
                flags=plan.flags,
                trigram_clauses=plan.clauses,
                top_k=top_k,
            )
            if regex_results is not None:
                return regex_results

        trigram_candidates = self.trigram.candidates(query)
        token_candidates = self.inverted.candidates(query)

        if trigram_candidates and token_candidates:
            candidates = trigram_candidates | token_candidates
        elif trigram_candidates:
            candidates = trigram_candidates
        else:
            candidates = token_candidates

        results: list[dict] = []
        q_norm = _normalize_text(query)
        for doc_id in candidates:
            doc = self.documents.get(doc_id)
            if not doc:
                continue
            trigram_score = self.trigram.overlap_ratio(doc_id, query)
            token_score = self.inverted.token_score(doc_id, query)
            phrase_bonus = 1.0 if q_norm and q_norm in _normalize_text(doc["text"]) else 0.0
            score = (0.55 * trigram_score) + (0.35 * token_score) + (0.10 * phrase_bonus)
            results.append(
                {
                    "id": doc_id,
                    "score": round(score, 6),
                    "text": doc["text"],
                    "metadata": doc["metadata"],
                    "source": "lexical",
                }
            )

        results.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
        return results[:top_k]

    def rg_search(self, query: str, top_k: int = 10) -> list[dict]:
        """Full-scan regex/text search baseline similar to rg-style scanning."""
        if not query.strip():
            return []

        plan = build_regex_query_plan(query)
        is_regex = bool(plan and plan.is_regex)

        compiled: re.Pattern[str] | None = None
        if is_regex and plan:
            try:
                compiled = re.compile(plan.pattern, plan.flags)
            except re.error:
                compiled = None

        results: list[dict] = []
        for doc_id, doc in self.documents.items():
            text = str(doc.get("text", ""))
            if not text:
                continue

            if compiled is not None:
                matches = list(compiled.finditer(text))
                if not matches:
                    continue
                total_match_len = sum(max(1, m.end() - m.start()) for m in matches)
                score = min(1.0, 0.5 + (0.5 * (total_match_len / max(1, len(text)))))
            else:
                q_tokens = _tokenize(query)
                if not q_tokens:
                    continue
                text_norm = _normalize_text(text)
                hit_tokens = sum(1 for token in q_tokens if token in text_norm)
                if hit_tokens == 0:
                    continue
                score = hit_tokens / len(q_tokens)

            results.append(
                {
                    "id": doc_id,
                    "score": round(float(score), 6),
                    "text": text,
                    "metadata": doc.get("metadata", {}),
                    "source": "rg",
                }
            )

        results.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
        return results[:top_k]

    def _search_regex(
        self,
        pattern: str,
        flags: int,
        trigram_clauses: list[set[str]],
        top_k: int,
    ) -> list[dict] | None:
        try:
            compiled = re.compile(pattern, flags)
        except re.error:
            # Invalid regex: caller will fall back to plain lexical search.
            return None

        candidates = self.trigram.candidates_from_clauses(trigram_clauses)
        if not candidates:
            candidates = set(self.trigram.doc_ids)

        results: list[dict] = []
        for doc_id in candidates:
            doc = self.documents.get(doc_id)
            if not doc:
                continue
            text = str(doc.get("text", ""))
            match = compiled.search(text)
            if not match:
                continue
            # Regex-verified result: correctness first; tie-break by match density.
            match_len = max(1, match.end() - match.start())
            score = round(min(1.0, 0.7 + (0.3 * (match_len / max(1, len(text))))), 6)
            results.append(
                {
                    "id": doc_id,
                    "score": score,
                    "text": text,
                    "metadata": doc.get("metadata", {}),
                    "source": "lexical",
                }
            )

        results.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
        return results[:top_k]
