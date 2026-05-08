"""Tests for ModelPolicy + LLMAgent.select_model() — L-03."""

from __future__ import annotations

import pytest

from uaaf.execution.llm_agent import LLMAgent, ModelPolicy
from uaaf.intent.models import ModelTier
from uaaf.providers.router import ModelRouter
from uaaf._testing.fakes import FakeLLMProvider


# ---------------------------------------------------------------------------
# ModelPolicy defaults
# ---------------------------------------------------------------------------

def test_model_policy_has_sensible_defaults() -> None:
    policy = ModelPolicy()
    assert isinstance(policy.keywords, set)
    assert len(policy.keywords) > 0
    assert policy.word_count_threshold > 0
    assert policy.cheap_threshold > 0
    assert policy.cheap_threshold < policy.word_count_threshold


# ---------------------------------------------------------------------------
# LLMAgent.select_model → ModelTier
# ---------------------------------------------------------------------------

def _make_fake_agent() -> LLMAgent:
    """Return a concrete LLMAgent subclass instance for testing select_model."""
    from dataclasses import dataclass
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


def test_select_model_short_query_returns_cheap() -> None:
    agent = _make_fake_agent()
    # Under cheap_threshold (default 5 words)
    tier = agent.select_model("list tasks")
    assert tier == ModelTier.CHEAP


def test_select_model_normal_query_returns_standard() -> None:
    agent = _make_fake_agent()
    # 10 words — above cheap, below word_count_threshold
    tier = agent.select_model("show me all tasks due this week for goal g1")
    assert tier == ModelTier.STANDARD


def test_select_model_long_query_returns_powerful() -> None:
    agent = _make_fake_agent()
    # Over word_count_threshold (default 25)
    long_query = " ".join(["word"] * 30)
    tier = agent.select_model(long_query)
    assert tier == ModelTier.POWERFUL


def test_select_model_keyword_match_returns_powerful() -> None:
    agent = _make_fake_agent()
    tier = agent.select_model("analyze the effort distribution across goals")
    assert tier == ModelTier.POWERFUL


def test_select_model_multiple_keywords_still_powerful() -> None:
    agent = _make_fake_agent()
    tier = agent.select_model("compare and evaluate all strategies")
    assert tier == ModelTier.POWERFUL


def test_select_model_keyword_case_insensitive() -> None:
    agent = _make_fake_agent()
    tier = agent.select_model("ANALYZE my portfolio")
    assert tier == ModelTier.POWERFUL


def test_select_model_uses_custom_policy() -> None:
    agent = _make_fake_agent()
    agent.model_policy = ModelPolicy(
        keywords={"custom"},
        word_count_threshold=100,
        cheap_threshold=1,
    )
    # "custom" keyword → POWERFUL
    assert agent.select_model("custom query") == ModelTier.POWERFUL
    # Short but above cheap_threshold=1 → STANDARD
    assert agent.select_model("hello world") == ModelTier.STANDARD


# ---------------------------------------------------------------------------
# ModelRouter._model_to_tier — recognize tier strings directly
# ---------------------------------------------------------------------------

def _make_router() -> ModelRouter:
    fake = FakeLLMProvider()
    return ModelRouter(providers={
        ModelTier.CHEAP: fake,
        ModelTier.STANDARD: fake,
        ModelTier.POWERFUL: fake,
    })


def test_model_router_recognizes_cheap_tier_string() -> None:
    router = _make_router()
    assert router._model_to_tier("cheap") == ModelTier.CHEAP


def test_model_router_recognizes_standard_tier_string() -> None:
    router = _make_router()
    assert router._model_to_tier("standard") == ModelTier.STANDARD


def test_model_router_recognizes_powerful_tier_string() -> None:
    router = _make_router()
    assert router._model_to_tier("powerful") == ModelTier.POWERFUL


def test_model_router_backward_compat_mini() -> None:
    router = _make_router()
    assert router._model_to_tier("gpt-4o-mini") == ModelTier.CHEAP


def test_model_router_backward_compat_opus() -> None:
    router = _make_router()
    assert router._model_to_tier("claude-opus-4") == ModelTier.POWERFUL


def test_model_router_backward_compat_standard_model() -> None:
    router = _make_router()
    assert router._model_to_tier("gpt-4o") == ModelTier.STANDARD
