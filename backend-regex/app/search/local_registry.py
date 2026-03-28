"""In-memory registry for lexical search indexes."""

from collections import defaultdict
from typing import Iterable

from app.search.cursor_like import CursorLikeIndex
from app.search.evidence import EvidenceUnit


class LocalSearchRegistry:
    """Keeps one lexical index per logical search index name."""

    def __init__(self):
        self._indexes: dict[str, CursorLikeIndex] = defaultdict(CursorLikeIndex)

    def add_evidence_units(self, index_name: str, evidence_units: list[EvidenceUnit]) -> int:
        docs = [
            {
                "id": unit.evidence_id,
                "text": unit.content,
                "metadata": {
                    "document_id": unit.document_id,
                    "source_type": unit.source_type,
                    "page_number": unit.page_number,
                    **unit.metadata,
                },
            }
            for unit in evidence_units
        ]
        self._indexes[index_name].add_documents(docs)
        return len(docs)

    @staticmethod
    def _filter_by_document_ids(results: list[dict], document_ids: Iterable[str] | None) -> list[dict]:
        if not document_ids:
            return results
        allowed = {str(item) for item in document_ids if str(item)}
        return [
            row for row in results
            if str((row.get("metadata") or {}).get("document_id") or "") in allowed
        ]

    def lexical_search(
        self,
        index_name: str,
        query: str,
        top_k: int = 10,
        document_ids: Iterable[str] | None = None,
    ) -> list[dict]:
        raw = self._indexes[index_name].search(query=query, top_k=max(top_k * 5, top_k))
        filtered = self._filter_by_document_ids(raw, document_ids)
        return filtered[:top_k]

    def rg_search(
        self,
        index_name: str,
        query: str,
        top_k: int = 10,
        document_ids: Iterable[str] | None = None,
    ) -> list[dict]:
        raw = self._indexes[index_name].rg_search(query=query, top_k=max(top_k * 5, top_k))
        filtered = self._filter_by_document_ids(raw, document_ids)
        return filtered[:top_k]


_registry = LocalSearchRegistry()


def get_local_search_registry() -> LocalSearchRegistry:
    return _registry
