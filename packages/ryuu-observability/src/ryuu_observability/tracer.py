"""OpenTelemetry-backed tracer with correlation-ID propagation.

Phase 9.3: Default span processor is `BatchSpanProcessor` (non-blocking export
via background thread). Opt-in to `SimpleSpanProcessor` via `processor="simple"`
for dev/debug (synchronous, deterministic for tests).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Literal

from opentelemetry import trace as otel_trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)

if TYPE_CHECKING:
    from opentelemetry.sdk.trace.export import SpanExporter

_correlation_id_var: ContextVar[str | None] = ContextVar("ryuu_correlation_id", default=None)


class Tracer:
    """Async-friendly OTel tracer with built-in correlation-ID management.

    Default: `BatchSpanProcessor` (non-blocking export, prod-grade).
    Override via `processor="simple"` for synchronous dev/test export.
    """

    def __init__(
        self,
        service_name: str = "ryuu",
        exporter: SpanExporter | None = None,
        processor: Literal["batch", "simple"] = "batch",
    ) -> None:
        resource = Resource.create({"service.name": service_name})
        self._provider = TracerProvider(resource=resource)
        exp = exporter or ConsoleSpanExporter()
        if processor == "simple":
            self._provider.add_span_processor(SimpleSpanProcessor(exp))
        else:
            self._provider.add_span_processor(BatchSpanProcessor(exp))
        self._otel = self._provider.get_tracer(service_name)

    @asynccontextmanager
    async def span(
        self,
        name: str,
        task_id: str | None = None,
        correlation_id: str | None = None,
        **attrs: Any,
    ) -> AsyncGenerator[str, None]:
        corr_id = correlation_id or get_current_correlation_id() or str(uuid.uuid4())
        token = _correlation_id_var.set(corr_id)

        span_attrs: dict[str, Any] = {"correlation_id": corr_id}
        if task_id is not None:
            span_attrs["task_id"] = task_id
        span_attrs.update(attrs)

        with self._otel.start_as_current_span(name, attributes=span_attrs):
            try:
                yield corr_id
            finally:
                _correlation_id_var.reset(token)

    def shutdown(self) -> None:
        self._provider.shutdown()


def get_current_correlation_id() -> str | None:
    return _correlation_id_var.get()


def setup_tracing(target: str = "console", service_name: str = "ryuu") -> None:
    """Configure the global OTel tracer provider."""
    if target == "console":
        exporter: SpanExporter = ConsoleSpanExporter()
    elif target.startswith("otlp://"):
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            exporter = OTLPSpanExporter(endpoint=target.removeprefix("otlp://"))
        except ImportError as exc:
            raise ImportError("Install opentelemetry-exporter-otlp-proto-grpc for OTLP export.") from exc
    else:
        raise ValueError(f"Unknown tracing target: {target!r}")

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    otel_trace.set_tracer_provider(provider)
