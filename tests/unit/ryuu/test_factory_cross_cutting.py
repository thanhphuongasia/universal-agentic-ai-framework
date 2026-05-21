"""Cross-cutting toggle tests — 5 toggles × 2 states = 10 cases.

Phase 10 T2.5. Expected RED until T5 implementation.

Toggles: budget_usd, rate_limit_rps, audit, trace, verbose.
Off (None/False) → NullObject. On → Real impl.
"""

from __future__ import annotations

import pytest

from ryuu.factory import Agent


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")


# ── budget_usd ──────────────────────────────────────────────────────────────


def test_budget_off_uses_null_cost_tracker() -> None:
    agent = Agent(model="gpt-4o-mini")
    from ryuu_core.nulls import NullCostTracker
    assert isinstance(agent._agent.cost_tracker, NullCostTracker)  # type: ignore[attr-defined]


def test_budget_on_uses_real_cost_tracker() -> None:
    agent = Agent(model="gpt-4o-mini", budget_usd=1.0)
    from ryuu_observability.cost import CostTracker
    assert isinstance(agent._agent.cost_tracker, CostTracker)  # type: ignore[attr-defined]


# ── rate_limit_rps ──────────────────────────────────────────────────────────


def test_rate_limit_off_uses_null() -> None:
    agent = Agent(model="gpt-4o-mini")
    from ryuu_core.nulls import NullRateLimiter
    assert isinstance(agent._agent.rate_limiter, NullRateLimiter)  # type: ignore[attr-defined]


def test_rate_limit_on_uses_real() -> None:
    agent = Agent(model="gpt-4o-mini", rate_limit_rps=10)
    from ryuu_observability.rate_limit import RateLimiter
    assert isinstance(agent._agent.rate_limiter, RateLimiter)  # type: ignore[attr-defined]


# ── audit ───────────────────────────────────────────────────────────────────


def test_audit_off_uses_null() -> None:
    agent = Agent(model="gpt-4o-mini")
    from ryuu_core.nulls import NullAuditLogger
    assert isinstance(agent._agent.audit_logger, NullAuditLogger)  # type: ignore[attr-defined]


def test_audit_on_uses_real() -> None:
    agent = Agent(model="gpt-4o-mini", audit=True)
    from ryuu_observability.audit import AuditLogger
    assert isinstance(agent._agent.audit_logger, AuditLogger)  # type: ignore[attr-defined]


# ── trace ───────────────────────────────────────────────────────────────────


def test_trace_off_uses_null() -> None:
    agent = Agent(model="gpt-4o-mini")
    from ryuu_core.nulls import NullTracer
    assert isinstance(agent._agent.tracer, NullTracer)  # type: ignore[attr-defined]


def test_trace_on_uses_real() -> None:
    agent = Agent(model="gpt-4o-mini", trace=True)
    from ryuu_observability.tracer import Tracer
    assert isinstance(agent._agent.tracer, Tracer)  # type: ignore[attr-defined]


# ── verbose ─────────────────────────────────────────────────────────────────


def test_verbose_off_no_console_output() -> None:
    """verbose=False → console handler NOT registered."""
    agent = Agent(model="gpt-4o-mini")
    # verbose flag should be False on internal agent
    assert getattr(agent._agent, "_verbose", False) is False  # type: ignore[attr-defined]


def test_verbose_on_console_output_enabled() -> None:
    """verbose=True → console output enabled."""
    agent = Agent(model="gpt-4o-mini", verbose=True)
    assert getattr(agent._agent, "_verbose", False) is True  # type: ignore[attr-defined]
