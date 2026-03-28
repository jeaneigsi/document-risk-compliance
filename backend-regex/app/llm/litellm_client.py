"""LiteLLM client wrapper for OpenRouter-backed generation."""

from typing import Any

from app.config import get_settings


class LiteLLMClient:
    """Thin async wrapper around LiteLLM completion."""

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str | None = None,
        timeout: int | None = None,
        input_price_per_1k: float | None = None,
        output_price_per_1k: float | None = None,
    ):
        settings = get_settings()
        self.api_key = api_key or settings.openrouter_api_key
        self.api_base = api_base or settings.openrouter_base_url
        self.default_model = default_model or settings.llm_default_model
        self.timeout = timeout or settings.llm_timeout
        self.input_price_per_1k = (
            settings.llm_input_price_per_1k if input_price_per_1k is None else input_price_per_1k
        )
        self.output_price_per_1k = (
            settings.llm_output_price_per_1k if output_price_per_1k is None else output_price_per_1k
        )

    async def analyze(
        self,
        prompt: str,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Run a completion and normalize response payload."""
        try:
            from litellm import acompletion  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("litellm must be installed to use LiteLLMClient") from exc

        used_model = model or self.default_model
        response = await acompletion(
            model=used_model,
            messages=[{"role": "user", "content": prompt}],
            api_key=self.api_key,
            api_base=self.api_base,
            timeout=self.timeout,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        content = response["choices"][0]["message"]["content"]
        usage = self._normalize_usage(response.get("usage"))
        return {
            "status": "completed",
            "model": used_model,
            "content": content,
            "usage": usage,
        }

    def analyze_sync(
        self,
        prompt: str,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Synchronous variant for non-async call sites."""
        try:
            from litellm import completion  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("litellm must be installed to use LiteLLMClient") from exc

        used_model = model or self.default_model
        response = completion(
            model=used_model,
            messages=[{"role": "user", "content": prompt}],
            api_key=self.api_key,
            api_base=self.api_base,
            timeout=self.timeout,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = response["choices"][0]["message"]["content"]
        usage = self._normalize_usage(response.get("usage"))
        return {
            "status": "completed",
            "model": used_model,
            "content": content,
            "usage": usage,
        }

    @staticmethod
    def _normalize_usage(usage: Any) -> dict[str, Any]:
        """Normalize LiteLLM usage object to plain dict for API responses."""
        if isinstance(usage, dict):
            return usage
        if usage is None:
            return {}
        if hasattr(usage, "model_dump"):
            return usage.model_dump()
        if hasattr(usage, "dict"):
            return usage.dict()
        if hasattr(usage, "__dict__"):
            raw = {k: v for k, v in vars(usage).items() if not k.startswith("_")}
            if raw:
                return raw
        fields = ("prompt_tokens", "completion_tokens", "total_tokens")
        extracted = {
            key: getattr(usage, key)
            for key in fields
            if hasattr(usage, key)
        }
        if extracted:
            return extracted
        return {}

    @staticmethod
    def estimate_cost(usage: dict[str, Any], input_price_per_1k: float, output_price_per_1k: float) -> float:
        """Estimate completion cost from usage counters."""
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))
        return (prompt_tokens / 1000.0) * input_price_per_1k + (completion_tokens / 1000.0) * output_price_per_1k
