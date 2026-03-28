"""Tests for LiteLLM client wrapper."""

import sys
import types

import pytest

from app.llm.litellm_client import LiteLLMClient


@pytest.mark.asyncio
async def test_litellm_client_analyze_async(monkeypatch):
    async def fake_acompletion(**kwargs):
        return {
            "choices": [{"message": {"content": "ok-async"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(acompletion=fake_acompletion))
    client = LiteLLMClient(api_key="x", api_base="https://openrouter.ai/api/v1", default_model="openrouter/test")
    result = await client.analyze("hello")
    assert result["status"] == "completed"
    assert result["content"] == "ok-async"


def test_litellm_client_analyze_sync(monkeypatch):
    def fake_completion(**kwargs):
        return {
            "choices": [{"message": {"content": "ok-sync"}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 8},
        }

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=fake_completion))
    client = LiteLLMClient(api_key="x", api_base="https://openrouter.ai/api/v1", default_model="openrouter/test")
    result = client.analyze_sync("hello")
    assert result["status"] == "completed"
    assert result["content"] == "ok-sync"


def test_estimate_cost():
    usage = {"prompt_tokens": 1000, "completion_tokens": 500}
    cost = LiteLLMClient.estimate_cost(usage, input_price_per_1k=0.001, output_price_per_1k=0.002)
    assert cost == 0.002


def test_litellm_client_normalizes_usage_object(monkeypatch):
    class UsageObj:
        prompt_tokens = 12
        completion_tokens = 4

    def fake_completion(**kwargs):
        return {
            "choices": [{"message": {"content": "ok-sync"}}],
            "usage": UsageObj(),
        }

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=fake_completion))
    client = LiteLLMClient(api_key="x", api_base="https://openrouter.ai/api/v1", default_model="openrouter/test")
    result = client.analyze_sync("hello")
    assert result["usage"]["prompt_tokens"] == 12
    assert result["usage"]["completion_tokens"] == 4
