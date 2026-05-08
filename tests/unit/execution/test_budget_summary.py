"""Tests for BudgetSummary + CONTEXT_WINDOW — L-04."""

from __future__ import annotations

import pytest

from uaaf.execution.llm_agent import BudgetSummary, LLMAgent
from uaaf.observability._pricing import CONTEXT_WINDOW
from uaaf.providers.llm import TokenUsage


# ---------------------------------------------------------------------------
# CONTEXT_WINDOW map in _pricing.py
# ---------------------------------------------------------------------------

def test_context_window_covers_common_openai_models() -> None:
    for model in ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"]:
        assert model in CONTEXT_WINDOW, f"{model} not in CONTEXT_WINDOW"
        assert CONTEXT_WINDOW[model] > 0


def test_context_window_covers_anthropic_models() -> None:
    for model in ["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5"]:
        assert model in CONTEXT_WINDOW, f"{model} not in CONTEXT_WINDOW"


# ---------------------------------------------------------------------------
# BudgetSummary dataclass
# ---------------------------------------------------------------------------

def test_budget_summary_has_required_fields() -> None:
    summary = BudgetSummary(
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        window_size=128_000,
        pct_used=0.117,
    )
    assert summary.input_tokens == 100
    assert summary.output_tokens == 50
    assert summary.total_tokens == 150
    assert summary.window_size == 128_000
    assert pytest.approx(summary.pct_used, abs=0.001) == 0.117


# ---------------------------------------------------------------------------
# LLMAgent.budget_summary() method
# ---------------------------------------------------------------------------

def _make_agent() -> LLMAgent:
    from dataclasses import dataclass
    from uaaf._testing.fakes import FakeLLMProvider
    from uaaf.execution.agent import AgentResult, Task
    from uaaf.observability.audit import AuditConfig, AuditLogger
    from uaaf.observability.cost import Cost, CostPolicy, CostTracker
    from uaaf.observability.rate_limit import RateLimiter, RatePolicy
    from uaaf.observability.tracer import Tracer
    from uaaf.runtime.context import ExecutionContext
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    @dataclass
    class StubAgent(LLMAgent):
        async def _execute(self, task: Task, context: ExecutionContext) -> AgentResult:
            raise NotImplementedError

    return StubAgent(
        agent_id="stub",
        cost_tracker=CostTracker(policy=CostPolicy()),
        tracer=Tracer(service_name="test", exporter=InMemorySpanExporter()),
        audit_logger=AuditLogger(AuditConfig(backend="console")),
        rate_limiter=RateLimiter(policy=RatePolicy(rps=1000.0, burst=100)),
        llm=FakeLLMProvider(),
    )


def test_budget_summary_known_model() -> None:
    agent = _make_agent()
    usage = TokenUsage(input_tokens=1000, output_tokens=500)
    summary = agent.budget_summary(usage, "gpt-4o")
    assert summary.input_tokens == 1000
    assert summary.output_tokens == 500
    assert summary.total_tokens == 1500
    assert summary.window_size == CONTEXT_WINDOW["gpt-4o"]
    expected_pct = 1500 / CONTEXT_WINDOW["gpt-4o"] * 100
    assert pytest.approx(summary.pct_used, rel=1e-3) == expected_pct


def test_budget_summary_unknown_model_fallback_128k() -> None:
    agent = _make_agent()
    usage = TokenUsage(input_tokens=100, output_tokens=50)
    summary = agent.budget_summary(usage, "unknown-model-xyz")
    assert summary.window_size == 128_000


def test_budget_summary_pct_used_calculation() -> None:
    agent = _make_agent()
    usage = TokenUsage(input_tokens=12_800, output_tokens=0)
    summary = agent.budget_summary(usage, "unknown-model-xyz")
    assert pytest.approx(summary.pct_used, rel=1e-3) == 10.0  # 12800/128000 * 100


def test_budget_summary_tier_string_fallback() -> None:
    """Tier strings like 'cheap'/'standard'/'powerful' are not in CONTEXT_WINDOW → use 128k."""
    agent = _make_agent()
    usage = TokenUsage(input_tokens=1000, output_tokens=1000)
    summary = agent.budget_summary(usage, "cheap")
    assert summary.window_size == 128_000
