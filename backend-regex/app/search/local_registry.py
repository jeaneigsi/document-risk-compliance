"""In-memory registry for lexical search indexes."""

from collections import defaultdict

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

    def lexical_search(self, index_name: str, query: str, top_k: int = 10) -> list[dict]:
        return self._indexes[index_name].search(query=query, top_k=top_k)

    def rg_search(self, index_name: str, query: str, top_k: int = 10) -> list[dict]:
        return self._indexes[index_name].rg_search(query=query, top_k=top_k)


_registry = LocalSearchRegistry()


def get_local_search_registry() -> LocalSearchRegistry:
    return _registry
