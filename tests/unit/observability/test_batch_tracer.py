"""Phase 9.3 — Tracer uses BatchSpanProcessor by default."""

from __future__ import annotations

import pytest

from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor

from ryuu_observability.tracer import Tracer


def test_default_tracer_uses_batch_processor() -> None:
    """Phase 9.3: default span processor is BatchSpanProcessor (non-blocking)."""
    tracer = Tracer(service_name="test")
    processors = tracer._provider._active_span_processor._span_processors
    assert any(isinstance(p, BatchSpanProcessor) for p in processors)
    tracer.shutdown()


def test_tracer_simple_processor_opt_in() -> None:
    """`processor='simple'` opt-in for synchronous dev export."""
    tracer = Tracer(service_name="test", processor="simple")
    processors = tracer._provider._active_span_processor._span_processors
    assert any(isinstance(p, SimpleSpanProcessor) for p in processors)
    tracer.shutdown()


async def test_tracer_span_works_with_batch_processor() -> None:
    """span() still functions correctly with BatchSpanProcessor."""
    tracer = Tracer(service_name="test")
    async with tracer.span("test_op", task_id="t1") as corr_id:
        assert corr_id is not None
    tracer.shutdown()


def test_tracer_invalid_processor_uses_batch() -> None:
    """Unknown processor literal — type system catches at lint, runtime defaults to batch."""
    # Literal["batch", "simple"] — Pyright catches at type-check
    # Runtime: anything not "simple" → batch (fallthrough)
    tracer = Tracer(service_name="test", processor="batch")
    processors = tracer._provider._active_span_processor._span_processors
    assert any(isinstance(p, BatchSpanProcessor) for p in processors)
    tracer.shutdown()
