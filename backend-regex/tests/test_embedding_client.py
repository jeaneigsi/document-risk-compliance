"""Tests for LiteLLM embedding client."""

import sys
import types

import pytest

from app.search.embedding_client import EmbeddingClient


@pytest.mark.asyncio
async def test_embed_texts_returns_vectors(monkeypatch):
    captured = {}

    async def fake_aembedding(**kwargs):
        captured.update(kwargs)
        return {
            "data": [
                {"embedding": [0.1, 0.2]},
                {"embedding": [0.3, 0.4]},
            ]
        }

    fake_module = types.SimpleNamespace(aembedding=fake_aembedding)
    monkeypatch.setitem(sys.modules, "litellm", fake_module)

    client = EmbeddingClient(
        model="qwen/qwen3-embedding-4b",
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        dimensions=1024,
    )
    vectors = await client.embed_texts(["alpha", "beta"])

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert captured["model"] == "qwen/qwen3-embedding-4b"
    assert captured["api_key"] == "test-key"
    assert captured["api_base"] == "https://openrouter.ai/api/v1"
    assert captured["dimensions"] == 1024


@pytest.mark.asyncio
async def test_embed_texts_empty_input_returns_empty():
    client = EmbeddingClient(model="qwen/qwen3-embedding-4b", api_key="x")
    assert await client.embed_texts([]) == []

