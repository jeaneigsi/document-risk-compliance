"""Embedding client via LiteLLM + OpenRouter."""

from typing import Any

from app.config import get_settings


class EmbeddingClient:
    """Generate text embeddings through LiteLLM."""

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        dimensions: int | None = None,
    ):
        settings = get_settings()
        self.model = model or settings.embedding_model
        self.api_key = api_key or settings.openrouter_api_key
        self.base_url = base_url or settings.openrouter_base_url
        self.dimensions = dimensions if dimensions is not None else settings.embedding_dimensions

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text."""
        if not texts:
            return []

        try:
            from litellm import aembedding  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("litellm must be installed to use EmbeddingClient") from exc

        params: dict[str, Any] = {
            "model": self.model,
            "input": texts,
            "api_key": self.api_key,
            "api_base": self.base_url,
        }
        if self.dimensions is not None:
            params["dimensions"] = self.dimensions

        response = await aembedding(**params)
        return [item["embedding"] for item in response["data"]]

