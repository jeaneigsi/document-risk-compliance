"""OpenTelemetry helpers with no-op fallback."""

from contextlib import contextmanager
from typing import Any

from app.config import get_settings


class _NoopSpan:
    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        pass


class _NoopTracer:
    @contextmanager
    def start_as_current_span(self, name: str):
        yield _NoopSpan()


def get_tracer():
    """Return OpenTelemetry tracer or no-op tracer."""
    settings = get_settings()
    if not settings.monitoring_enabled:
        return _NoopTracer()

    try:
        from opentelemetry import trace  # type: ignore
    except Exception:
        return _NoopTracer()
    return trace.get_tracer(settings.otel_service_name)


@contextmanager
def start_span(name: str, attributes: dict[str, Any] | None = None):
    """Start a span and safely attach attributes."""
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as span:
        for key, value in (attributes or {}).items():
            try:
                span.set_attribute(key, value)
            except Exception:
                pass
        yield span

