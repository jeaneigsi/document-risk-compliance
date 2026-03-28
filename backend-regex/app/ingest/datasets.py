"""Dataset loading helpers for Phase 2 experimentation."""

import os
from typing import Any

from app.config import get_settings


def _sanitize_hf_token(raw: str | None) -> str | None:
    if not raw:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    if "#" in cleaned:
        cleaned = cleaned.split("#", 1)[0].strip()
    if " " in cleaned:
        cleaned = cleaned.split(" ", 1)[0].strip()
    if (cleaned.startswith('"') and cleaned.endswith('"')) or (
        cleaned.startswith("'") and cleaned.endswith("'")
    ):
        cleaned = cleaned[1:-1].strip()
    return cleaned or None


def _resolve_hf_token() -> str | None:
    settings = get_settings()
    return _sanitize_hf_token(
        os.getenv("HF_TOKEN")
        or os.getenv("HUGGINGFACE_HUB_TOKEN")
        or settings.hf_token
        or settings.huggingface_hub_token
    )


def load_hf_dataset(name: str, split: str | None = None, **kwargs: Any):
    """Load a Hugging Face dataset lazily."""

    try:
        from datasets import load_dataset  # type: ignore
    except ImportError as exc:  # pragma: no cover - validated via tests
        raise RuntimeError(
            "The `datasets` package is required to load benchmark datasets"
        ) from exc

    token = _resolve_hf_token()
    if "token" not in kwargs:
        if token:
            kwargs["token"] = token
        elif name == "kensho/FIND":
            # For gated FIND dataset, allow using local `hf auth login` token.
            kwargs["token"] = True

    if split is None:
        return load_dataset(name, **kwargs)
    return load_dataset(name, split=split, **kwargs)


def load_find_dataset(split: str = "validation"):
    return load_hf_dataset("kensho/FIND", split=split)


def load_wikipedia_contradict(split: str = "train"):
    return load_hf_dataset("ibm-research/Wikipedia_contradict_benchmark", split=split)


def load_longbench(split: str = "test"):
    return load_hf_dataset("yanbingzheng/LongBench", split=split)
