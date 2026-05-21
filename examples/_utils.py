"""Shared utilities for all RYUU examples."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from ryuu.observability.tracer import Tracer


class _SilentExporter(SpanExporter):
    """Drops all spans — keeps example output clean."""

    def export(self, spans: Sequence[Any]) -> SpanExportResult:
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass


def silent_tracer() -> Tracer:
    """Return a Tracer that discards all spans (no stdout noise)."""
    return Tracer(exporter=_SilentExporter())
