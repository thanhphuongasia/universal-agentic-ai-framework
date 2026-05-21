"""Tests for DirectStrategy — P1-T04."""

from __future__ import annotations

import pytest

from ryuu.cognitive.strategies.direct import DirectStrategy
from ryuu.intent.models import (
    DIRECT,
    CognitiveResult,
    ComplexityLevel,
    CostEstimate,
    StructuredIntent,
)
from ryuu_workflow.context import ContextScope, ExecutionContext


def _intent(complexity: ComplexityLevel = ComplexityLevel.LOW) -> StructuredIntent:
    return StructuredIntent(
        intent_type="query",
        action="search",
        entities={},
        complexity=complexity,
        confidence=0.9,
    )


def _ctx() -> ExecutionContext:
    return ExecutionContext(
        scope=ContextScope(user_id="u1", session_id="s1", domain="test"),
        correlation_id="c1",
    )


# ---------------------------------------------------------------------------
# applicable
# ---------------------------------------------------------------------------


def test_direct_strategy_always_applicable_low() -> None:
    s = DirectStrategy()
    assert s.applicable(_intent(ComplexityLevel.LOW), _ctx()) is True


def test_direct_strategy_always_applicable_high() -> None:
    s = DirectStrategy()
    assert s.applicable(_intent(ComplexityLevel.HIGH), _ctx()) is True


def test_direct_strategy_id() -> None:
    assert DirectStrategy().strategy_id == DIRECT


# ---------------------------------------------------------------------------
# estimate_cost
# ---------------------------------------------------------------------------


def test_direct_strategy_estimate_cost() -> None:
    cost = DirectStrategy().estimate_cost(_intent(), _ctx())
    assert isinstance(cost, CostEstimate)
    assert cost.steps_est == 1
    assert cost.usd_est >= 0.0


# ---------------------------------------------------------------------------
# execute
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_direct_executes_single_dispatch() -> None:
    from ryuu._testing.fakes import FakeAgentPool, FakeVerifier
    from ryuu.execution.agent import AgentResult
    from ryuu.observability.cost import Cost

    pool = FakeAgentPool(responses=[
        AgentResult(
            task_id="t1",
            output="answer to the query",
            cost=Cost(input_tokens=10, output_tokens=5, usd=0.001, provider="fake", model="fake"),
        )
    ])
    verifier = FakeVerifier()
    result = await DirectStrategy().execute(_intent(), _ctx(), pool, verifier)

    assert isinstance(result, CognitiveResult)
    assert result.content == "answer to the query"
    assert result.strategy_id == DIRECT
    assert pool.dispatch_count == 1


@pytest.mark.anyio
async def test_direct_execute_carries_intent_type_in_task() -> None:
    from ryuu._testing.fakes import FakeAgentPool, FakeVerifier
    from ryuu.execution.agent import AgentResult
    from ryuu.observability.cost import Cost

    pool = FakeAgentPool(responses=[
        AgentResult(task_id="t1", output="ok", cost=Cost.zero())
    ])
    intent = _intent()
    await DirectStrategy().execute(intent, _ctx(), pool, verifier=FakeVerifier())
    dispatched = pool.last_dispatched
    assert dispatched is not None
    assert dispatched.payload.get("intent_type") == intent.intent_type
