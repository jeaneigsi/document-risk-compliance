"""Langfuse tracker wrapper with safe fallback."""

import uuid
from typing import Any

from app.config import get_settings


class LangfuseTracker:
    """Lightweight wrapper around Langfuse SDK."""

    def __init__(self):
        settings = get_settings()
        self.enabled = (
            settings.monitoring_enabled
            and bool(settings.langfuse_public_key)
            and bool(settings.langfuse_secret_key)
        )
        self._client = None

        if self.enabled:
            try:
                from langfuse import Langfuse  # type: ignore

                self._client = Langfuse(
                    public_key=settings.langfuse_public_key,
                    secret_key=settings.langfuse_secret_key,
                    host=settings.langfuse_host,
                )
            except Exception:
                self._client = None

    def _new_trace_id(self) -> str:
        return str(uuid.uuid4())

    def trace(
        self,
        name: str,
        input_payload: Any,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        trace_id = self._new_trace_id()
        if not self._client:
            return trace_id
        try:
            trace = self._client.trace(
                id=trace_id,
                name=name,
                input=input_payload,
                metadata=metadata or {},
            )
            return getattr(trace, "id", trace_id)
        except Exception:
            return trace_id

    def event(
        self,
        trace_id: str,
        name: str,
        output: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self._client:
            return
        try:
            self._client.event(
                trace_id=trace_id,
                name=name,
                output=output,
                metadata=metadata or {},
            )
        except Exception:
            return


_tracker: LangfuseTracker | None = None


def get_langfuse_tracker() -> LangfuseTracker:
    global _tracker
    if _tracker is None:
        _tracker = LangfuseTracker()
    return _tracker

