"""pytest fixtures re-exported for product-side tests.

Usage in a product's conftest.py::

    from ryuu._testing.fixtures import *   # noqa: F401,F403
    # or selectively:
    from ryuu._testing.fixtures import tracer_fixture, cost_tracker_fixture
"""

from __future__ import annotations

import pytest

from ryuu._testing.fakes import FakeLLMProvider
from ryuu.observability.audit import AuditConfig, AuditLogger
from ryuu.observability.cost import CostPolicy, CostTracker
from ryuu.observability.rate_limit import RateLimiter, RatePolicy
from ryuu.observability.tracer import Tracer


@pytest.fixture
def tracer_fixture() -> Tracer:
    """Pre-configured Tracer with console exporter (no stderr noise in test)."""
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    return Tracer(service_name="test", exporter=InMemorySpanExporter())


@pytest.fixture
def cost_tracker_fixture() -> CostTracker:
    return CostTracker(policy=CostPolicy(per_user_per_day_usd=10.0))


@pytest.fixture
def audit_fixture() -> AuditLogger:
    return AuditLogger(config=AuditConfig(backend="console"))


@pytest.fixture
def rate_limiter_fixture() -> RateLimiter:
    return RateLimiter(policy=RatePolicy(rps=1000.0, burst=1000))


@pytest.fixture
def fake_llm_fixture() -> FakeLLMProvider:
    return FakeLLMProvider(default_content="test response")
