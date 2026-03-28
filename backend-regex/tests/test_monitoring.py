"""Tests for monitoring wrappers."""

import sys
import types

from app.monitor.langfuse import LangfuseTracker
from app.monitor.telemetry import start_span


def test_start_span_noop_fallback():
    with start_span("unit.test.span", {"k": "v"}) as span:
        span.set_attribute("a", 1)
        span.add_event("evt", {"x": 1})


def test_langfuse_tracker_without_keys_is_safe():
    tracker = LangfuseTracker()
    trace_id = tracker.trace("test", {"a": 1})
    assert isinstance(trace_id, str)
    tracker.event(trace_id, "event", {"ok": True})


def test_langfuse_tracker_with_fake_sdk(monkeypatch):
    class _FakeTrace:
        def __init__(self, trace_id):
            self.id = trace_id

    class _FakeLangfuse:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def trace(self, id, name, input, metadata):
            return _FakeTrace(id)

        def event(self, trace_id, name, output, metadata):
            return None

    monkeypatch.setitem(sys.modules, "langfuse", types.SimpleNamespace(Langfuse=_FakeLangfuse))
    from app.config import settings

    monkeypatch.setattr(settings, "monitoring_enabled", True)
    monkeypatch.setattr(settings, "langfuse_public_key", "pk")
    monkeypatch.setattr(settings, "langfuse_secret_key", "sk")

    tracker = LangfuseTracker()
    trace_id = tracker.trace("test", {"a": 1})
    assert isinstance(trace_id, str)
    tracker.event(trace_id, "event", {"ok": True})

