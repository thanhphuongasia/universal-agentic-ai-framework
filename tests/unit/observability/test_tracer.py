"""Tests for ryuu.observability.tracer — T03."""

from __future__ import annotations

import pytest

from ryuu.observability.tracer import Tracer, get_current_correlation_id


def _make_tracer() -> Tracer:
    """Return a Tracer with in-memory exporter to avoid console noise."""
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    return Tracer(service_name="test", exporter=InMemorySpanExporter())


# ---------------------------------------------------------------------------
# Basic span lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_span_enters_and_exits() -> None:
    tracer = _make_tracer()
    entered = False
    async with tracer.span("my-span") as corr_id:
        entered = True
        assert corr_id is not None
        assert len(corr_id) > 0
    assert entered


@pytest.mark.anyio
async def test_span_yields_correlation_id() -> None:
    tracer = _make_tracer()
    async with tracer.span("s", correlation_id="fixed-corr-id") as corr_id:
        assert corr_id == "fixed-corr-id"


@pytest.mark.anyio
async def test_span_auto_generates_correlation_id_when_not_given() -> None:
    tracer = _make_tracer()
    async with tracer.span("s") as corr_id:
        assert len(corr_id) == 36  # UUID4 format


# ---------------------------------------------------------------------------
# Correlation-ID propagation via context var
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_correlation_id_visible_inside_span() -> None:
    tracer = _make_tracer()
    async with tracer.span("s", correlation_id="cid-abc") as corr_id:
        assert get_current_correlation_id() == "cid-abc"
        assert corr_id == "cid-abc"


@pytest.mark.anyio
async def test_correlation_id_cleared_after_span_exits() -> None:
    tracer = _make_tracer()
    async with tracer.span("s", correlation_id="cid-xyz"):
        pass
    # After exit, context var should be reset (not necessarily None — depends on outer context)
    # Key invariant: a fresh call with no outer span has no leaked ID.
    # We test this by checking a fresh tracer span auto-generates its own ID.
    async with tracer.span("s2") as corr_id2:
        assert corr_id2 != "cid-xyz"


# ---------------------------------------------------------------------------
# Nested spans
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_nested_spans_preserve_outer_correlation_id() -> None:
    tracer = _make_tracer()
    async with tracer.span("outer", correlation_id="outer-cid") as outer_id:
        async with tracer.span("inner") as inner_id:
            # Inner span auto-inherits outer correlation_id if not specified.
            assert inner_id == "outer-cid"
        assert outer_id == "outer-cid"


@pytest.mark.anyio
async def test_nested_spans_can_override_correlation_id() -> None:
    tracer = _make_tracer()
    async with tracer.span("outer", correlation_id="outer-cid"):
        async with tracer.span("inner", correlation_id="inner-cid") as inner_id:
            assert inner_id == "inner-cid"
        # After inner exits, outer id is restored.
        assert get_current_correlation_id() == "outer-cid"
