"""Tests for NextPlaid client."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.search.nextplaid_client import NextPlaidClient


@pytest.mark.asyncio
async def test_health_check_success():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_client)
    cm.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=cm):
        client = NextPlaidClient(base_url="http://localhost:8081")
        assert await client.health_check() is True


@pytest.mark.asyncio
async def test_search_parses_results_from_dict():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"results": [{"id": "a", "score": 0.8}]}

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_client)
    cm.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=cm):
        client = NextPlaidClient(base_url="http://localhost:8081")
        results = await client.search("budget", index_name="docs", top_k=5)

    assert results == [{"id": "a", "score": 0.8}]


@pytest.mark.asyncio
async def test_index_evidence_units():
    create_response = MagicMock()
    create_response.status_code = 200
    create_response.raise_for_status = MagicMock()
    create_response.json.return_value = {"status": "ok", "index": "docs"}

    add_response = MagicMock()
    add_response.status_code = 200
    add_response.raise_for_status = MagicMock()
    add_response.json.return_value = {"status": "ok", "indexed": 1}

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=[create_response, add_response])

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_client)
    cm.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=cm):
        client = NextPlaidClient(base_url="http://localhost:8081")
        from app.search.evidence import EvidenceUnit

        payload = [
            EvidenceUnit(
                evidence_id="ev-1",
                document_id="doc-1",
                content="hello",
                source_type="text_span",
                page_number=1,
                metadata={"k": "v"},
            )
        ]
        result = await client.index_evidence_units(payload, index_name="docs")

    assert result["status"] == "ok"
    assert mock_client.post.await_count == 2


@pytest.mark.asyncio
async def test_index_evidence_units_fallback_on_404():
    create_first = MagicMock()
    create_first.status_code = 404
    create_first.raise_for_status = MagicMock()

    create_second = MagicMock()
    create_second.status_code = 409
    create_second.raise_for_status = MagicMock()
    create_second.json.return_value = {"status": "exists"}

    add_first = MagicMock()
    add_first.status_code = 404
    add_first.raise_for_status = MagicMock()

    add_second = MagicMock()
    add_second.status_code = 200
    add_second.raise_for_status = MagicMock()
    add_second.json.return_value = {"status": "ok", "indexed": 1}

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=[create_first, create_second, add_first, add_second])

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_client)
    cm.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=cm):
        client = NextPlaidClient(base_url="http://localhost:8081")
        from app.search.evidence import EvidenceUnit

        payload = [
            EvidenceUnit(
                evidence_id="ev-1",
                document_id="doc-1",
                content="hello",
                source_type="text_span",
                page_number=1,
                metadata={"k": "v"},
            )
        ]
        result = await client.index_evidence_units(payload, index_name="docs")

    assert result["status"] == "ok"
    assert mock_client.post.await_count == 4
