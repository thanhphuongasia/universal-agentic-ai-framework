"""Phase 14.3 — AdaptiveStrategy tests (Layer A). 5 cases."""

from __future__ import annotations

import pytest

from ryuu_cognitive.strategies.adaptive_strategy import AdaptiveStrategy
from ryuu_core.context import ContextScope, ExecutionContext
from ryuu_core.models import (
    AgentResult,
    ComplexityLevel,
    Cost,
    StructuredIntent,
    Task,
)


def _intent(action: str) -> StructuredIntent:
    return StructuredIntent(
        intent_type="query", action=action, entities={},
        complexity=ComplexityLevel.LOW, confidence=0.9,
    )


def _ctx() -> ExecutionContext:
    return ExecutionContext(
        scope=ContextScope(user_id="u", session_id="s", domain="t"),
        correlation_id="c1",
    )


class _CaptureAgentPool:
    """Captures dispatched task to inspect tier hints."""

    last_task: Task | None = None

    async def dispatch(self, task: Task) -> AgentResult:
        self.last_task = task
        return AgentResult(
            task_id=task.task_id, output="result",
            cost=Cost(input_tokens=10, output_tokens=5, usd=0.0001, provider="f", model="f"),
        )


class _NoopVerifier:
    async def verify(self, *args, **kwargs): return None


async def test_adaptive_trivial_uses_cheap_tier() -> None:
    """Short greeting → trivial tier → gpt-4o-mini, max_iter=2, max_tokens=300."""
    pool = _CaptureAgentPool()
    strategy = AdaptiveStrategy()
    await strategy.execute(_intent("hi"), _ctx(), pool, _NoopVerifier())

    assert pool.last_task is not None
    payload = pool.last_task.payload
    assert payload["difficulty"] == "trivial"
    assert payload["tier_model"] == "gpt-4o-mini"
    assert payload["tier_max_iterations"] == 2


async def test_adaptive_hard_uses_powerful_tier() -> None:
    """Analyze keyword → hard → gpt-4o + max_iter=8 + max_tokens=2000."""
    pool = _CaptureAgentPool()
    strategy = AdaptiveStrategy()
    await strategy.execute(
        _intent("Analyze the architecture and trace control flow"),
        _ctx(), pool, _NoopVerifier(),
    )
    assert pool.last_task is not None
    assert pool.last_task.payload["difficulty"] == "hard"
    assert pool.last_task.payload["tier_model"] == "gpt-4o"
    assert pool.last_task.payload["tier_max_iterations"] == 8


async def test_adaptive_custom_difficulty_fn() -> None:
    """User-supplied `difficulty_fn` overrides heuristic."""
    pool = _CaptureAgentPool()
    strategy = AdaptiveStrategy(
        difficulty_fn=lambda q: "hard",   # always hard
    )
    await strategy.execute(_intent("hi"), _ctx(), pool, _NoopVerifier())
    assert pool.last_task is not None
    assert pool.last_task.payload["difficulty"] == "hard"


async def test_adaptive_custom_tier_models() -> None:
    """`tier_models` override default mapping."""
    pool = _CaptureAgentPool()
    strategy = AdaptiveStrategy(
        difficulty_fn=lambda q: "trivial",
        tier_models={"trivial": "gpt-3.5-turbo", "medium": "x", "hard": "y"},
    )
    await strategy.execute(_intent("hi"), _ctx(), pool, _NoopVerifier())
    assert pool.last_task is not None
    assert pool.last_task.payload["tier_model"] == "gpt-3.5-turbo"


async def test_adaptive_strategy_id_and_universal() -> None:
    s = AdaptiveStrategy()
    assert s.strategy_id == "adaptive"
    assert s.applicable(_intent("x"), _ctx()) is True
