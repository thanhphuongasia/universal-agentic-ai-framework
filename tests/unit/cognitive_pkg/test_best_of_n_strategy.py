"""Phase 14.2 — BestOfNStrategy tests (Layer A).

6 cases. Strategy samples N candidates + aggregates via vote mode.

Vote modes:
  - "majority"   — Counter most_common (default)
  - "llm_judge"  — verifier scores each, pick max
  - "score_fn"   — user-supplied callable scores
"""

from __future__ import annotations

from collections import deque

import pytest

from ryuu_cognitive.strategies.best_of_n_strategy import BestOfNStrategy
from ryuu_core.context import ContextScope, ExecutionContext
from ryuu_core.models import (
    AgentResult,
    CognitiveResult,
    ComplexityLevel,
    Cost,
    StructuredIntent,
    Task,
)


def _make_intent() -> StructuredIntent:
    return StructuredIntent(
        intent_type="query", action="test", entities={},
        complexity=ComplexityLevel.LOW, confidence=0.9,
    )


def _make_ctx() -> ExecutionContext:
    return ExecutionContext(
        scope=ContextScope(user_id="u", session_id="s", domain="t"),
        correlation_id="c1",
    )


class _QueueAgentPool:
    """Returns canned outputs in order from queue."""

    def __init__(self, outputs: list[str]) -> None:
        self._queue: deque[str] = deque(outputs)
        self.call_count = 0

    async def dispatch(self, task: Task) -> AgentResult:
        self.call_count += 1
        out = self._queue.popleft() if self._queue else "fallback"
        return AgentResult(
            task_id=task.task_id, output=out,
            cost=Cost(input_tokens=10, output_tokens=5, usd=0.0001, provider="f", model="f"),
        )


class _NoopVerifier:
    async def verify(self, *args, **kwargs): return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_best_of_n_majority_vote() -> None:
    """3 samples, 2 agree → majority winner."""
    pool = _QueueAgentPool(["A", "B", "A"])
    strategy = BestOfNStrategy(n=3, vote="majority")
    result = await strategy.execute(_make_intent(), _make_ctx(), pool, _NoopVerifier())
    assert result.content == "A"
    assert pool.call_count == 3


async def test_best_of_n_score_fn_mode() -> None:
    """score_fn picks highest-scoring sample."""
    pool = _QueueAgentPool(["short", "longest_one_wins", "mid"])
    strategy = BestOfNStrategy(
        n=3, vote="score_fn", score_fn=lambda s: len(s),
    )
    result = await strategy.execute(_make_intent(), _make_ctx(), pool, _NoopVerifier())
    assert result.content == "longest_one_wins"


async def test_best_of_n_n_equals_1_acts_as_primary() -> None:
    """n=1 → single dispatch, no aggregation overhead."""
    pool = _QueueAgentPool(["only"])
    strategy = BestOfNStrategy(n=1, vote="majority")
    result = await strategy.execute(_make_intent(), _make_ctx(), pool, _NoopVerifier())
    assert result.content == "only"
    assert pool.call_count == 1


async def test_best_of_n_strategy_id() -> None:
    assert BestOfNStrategy().strategy_id == "best_of_n"


async def test_best_of_n_applicable_universal() -> None:
    assert BestOfNStrategy().applicable(_make_intent(), _make_ctx()) is True


async def test_best_of_n_estimate_cost_scales_with_n() -> None:
    """estimate_cost reflects N× base cost."""
    s1 = BestOfNStrategy(n=1)
    s5 = BestOfNStrategy(n=5)
    e1 = s1.estimate_cost(_make_intent(), _make_ctx())
    e5 = s5.estimate_cost(_make_intent(), _make_ctx())
    assert e5.input_tokens_est >= e1.input_tokens_est * 3   # at least 3x
