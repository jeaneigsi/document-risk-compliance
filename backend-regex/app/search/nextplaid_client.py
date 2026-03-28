"""HTTP client for NextPlaid search service."""

from typing import Any

import httpx

from app.config import get_settings
from app.search.evidence import EvidenceUnit


class NextPlaidClient:
    """Minimal async client for NextPlaid APIs."""

    def __init__(self, base_url: str | None = None, timeout: int | None = None):
        settings = get_settings()
        self.base_url = (base_url or settings.next_plaid_url).rstrip("/")
        self.timeout = timeout or settings.next_plaid_timeout
        self._known_indices: set[str] = set()

    async def health_check(self) -> bool:
        """Return True if NextPlaid is reachable."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}/health")
                return response.status_code == 200
        except Exception:
            return False

    async def search(
        self,
        query: str,
        index_name: str = "default",
        top_k: int = 10,
        document_ids: list[str] | None = None,
        filters: dict[str, Any] | None = None,
        filter_condition: str | None = None,
        filter_parameters: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Perform semantic search on a NextPlaid index (late-interaction model server-side)."""
        params: dict[str, Any] = {"top_k": top_k}
        merged_filters = dict(filters or {})
        if document_ids:
            merged_filters["document_id"] = [str(item) for item in document_ids if str(item)]
        if merged_filters:
            params["filters"] = merged_filters
        if filter_condition:
            params["filter_condition"] = filter_condition
        if filter_parameters:
            params["filter_parameters"] = filter_parameters

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/indices/{index_name}/search_with_encoding",
                json={
                    "queries": [query],
                    "params": params,
                },
            )
            if response.status_code != 404:
                response.raise_for_status()
                return self._parse_search_results(response.json())

            # Legacy fallback.
            response = await client.post(
                f"{self.base_url}/indexes/{index_name}/search",
                json={
                    "query": query,
                    "top_k": top_k,
                    **({"filters": merged_filters} if merged_filters else {}),
                },
            )
            if response.status_code == 404:
                return []
            response.raise_for_status()
            return self._parse_search_results(response.json())

    async def create_index(
        self,
        index_name: str,
        nbits: int = 4,
    ) -> dict[str, Any]:
        """Create a NextPlaid index if it does not exist."""
        if index_name in self._known_indices:
            return {"status": "exists", "name": index_name}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            # NextPlaid native shape (close to python client semantics).
            response = await client.post(
                f"{self.base_url}/indices",
                json={
                    "name": index_name,
                    "config": {"nbits": nbits},
                },
            )
            if response.status_code == 404:
                # Fallback schema variant.
                response = await client.post(
                    f"{self.base_url}/indices",
                    json={"name": index_name, "nbits": nbits},
                )
            if response.status_code not in (200, 201, 409):
                response.raise_for_status()

            try:
                data = response.json()
            except Exception:
                data = {"status": "ok", "name": index_name}

        self._known_indices.add(index_name)
        return data if isinstance(data, dict) else {"status": "ok", "name": index_name}

    async def add(
        self,
        index_name: str,
        documents: list[str],
        metadata: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Add documents to an index using server-side encoding."""
        payload: dict[str, Any] = {"documents": documents}
        if metadata is not None:
            payload["metadata"] = metadata

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/indices/{index_name}/update_with_encoding",
                json=payload,
            )
            if response.status_code == 404:
                # Legacy fallback.
                response = await client.post(
                    f"{self.base_url}/indexes/{index_name}/documents",
                    json={
                        "documents": [
                            {
                                "id": str(item.get("id", i)) if isinstance(item, dict) else str(i),
                                "text": documents[i],
                                "metadata": item if isinstance(item, dict) else {},
                            }
                            for i, item in enumerate(metadata or [{} for _ in documents])
                        ]
                    },
                )
            response.raise_for_status()
            try:
                data = response.json()
            except Exception:
                data = {"status": "accepted"}

        if isinstance(data, dict):
            return data
        return {"status": "ok", "indexed_count": len(documents)}

    async def delete(
        self,
        index_name: str,
        filter_condition: str,
        filter_parameters: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Delete documents by predicate."""
        payload = {
            "filter_condition": filter_condition,
            "filter_parameters": filter_parameters or [],
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/indices/{index_name}/delete",
                json=payload,
            )
            if response.status_code == 404:
                response = await client.post(
                    f"{self.base_url}/indices/{index_name}/delete_by_predicate",
                    json=payload,
                )
            response.raise_for_status()
            try:
                data = response.json()
            except Exception:
                data = {"status": "accepted"}
        return data if isinstance(data, dict) else {"status": "ok"}

    async def index_evidence_units(
        self,
        evidence_units: list[EvidenceUnit],
        index_name: str = "default",
        nbits: int = 4,
    ) -> dict[str, Any]:
        """Index evidence units into NextPlaid."""
        documents = [unit.content for unit in evidence_units]
        metadata = [
            {
                "id": unit.evidence_id,
                "document_id": unit.document_id,
                "source_type": unit.source_type,
                "page_number": unit.page_number,
                **unit.metadata,
            }
            for unit in evidence_units
        ]
        await self.create_index(index_name=index_name, nbits=nbits)
        return await self.add(
            index_name=index_name,
            documents=documents,
            metadata=metadata,
        )

    @staticmethod
    def _parse_search_results(data: Any) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return data

        if not isinstance(data, dict):
            return []

        # Older payload variants.
        if "results" in data and isinstance(data["results"], list):
            results = data["results"]
            if results and isinstance(results[0], dict) and "document_ids" in results[0]:
                first = results[0]
                doc_ids = first.get("document_ids") or []
                scores = first.get("scores") or []
                metadata = first.get("metadata") or []
                rows: list[dict[str, Any]] = []
                for i, doc_id in enumerate(doc_ids):
                    meta = metadata[i] if i < len(metadata) else None
                    score = float(scores[i]) if i < len(scores) else 0.0
                    item_id = str(doc_id)
                    if isinstance(meta, dict):
                        item_id = str(meta.get("id") or meta.get("document_id") or doc_id)
                    rows.append(
                        {
                            "id": item_id,
                            "score": score,
                            "metadata": meta if isinstance(meta, dict) else {},
                        }
                    )
                return rows
            return results

        if "data" in data and isinstance(data["data"], list):
            return data["data"]

        return []
