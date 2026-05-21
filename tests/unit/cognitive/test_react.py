"""Tests for ReActStrategy — P1-T05."""

from __future__ import annotations

import pytest

from ryuu.cognitive.strategies.react import ReActStrategy
from ryuu.intent.models import REACT, CognitiveResult, ComplexityLevel, StructuredIntent
from ryuu_workflow.context import ContextScope, ExecutionContext


def _intent(complexity: ComplexityLevel = ComplexityLevel.MEDIUM) -> StructuredIntent:
    return StructuredIntent(
        intent_type="analysis",
        action="trace",
        entities={"class": "UserService"},
        complexity=complexity,
        confidence=0.85,
    )


def _ctx() -> ExecutionContext:
    return ExecutionContext(
        scope=ContextScope(user_id="u1", session_id="s1", domain="test"),
        correlation_id="c1",
    )


# ---------------------------------------------------------------------------
# applicable
# ---------------------------------------------------------------------------


def test_react_applicable_on_medium() -> None:
    assert ReActStrategy().applicable(_intent(ComplexityLevel.MEDIUM), _ctx()) is True


def test_react_applicable_on_high() -> None:
    assert ReActStrategy().applicable(_intent(ComplexityLevel.HIGH), _ctx()) is True


def test_react_not_applicable_on_low() -> None:
    assert ReActStrategy().applicable(_intent(ComplexityLevel.LOW), _ctx()) is False


def test_react_strategy_id() -> None:
    assert ReActStrategy().strategy_id == REACT


# ---------------------------------------------------------------------------
# execute — DONE on first step
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_react_terminates_on_done_signal() -> None:
    from ryuu._testing.fakes import FakeAgentPool, FakeVerifier
    from ryuu.execution.agent import AgentResult
    from ryuu.observability.cost import Cost

    pool = FakeAgentPool(responses=[
        AgentResult(task_id="t1", output="DONE:UserService depends on OrderService", cost=Cost.zero()),
    ])
    result = await ReActStrategy().execute(_intent(), _ctx(), pool, FakeVerifier())
    assert isinstance(result, CognitiveResult)
    assert "UserService" in result.content
    assert result.strategy_id == REACT
    assert pool.dispatch_count == 1


@pytest.mark.anyio
async def test_react_loops_until_done() -> None:
    from ryuu._testing.fakes import FakeAgentPool, FakeVerifier
    from ryuu.execution.agent import AgentResult
    from ryuu.observability.cost import Cost

    pool = FakeAgentPool(responses=[
        AgentResult(task_id="t1", output="ACTION:query(UserService)", cost=Cost.zero()),
        AgentResult(task_id="t2", output="ACTION:query(OrderService)", cost=Cost.zero()),
        AgentResult(task_id="t3", output="DONE:found 2 dependencies", cost=Cost.zero()),
    ])
    result = await ReActStrategy().execute(_intent(), _ctx(), pool, FakeVerifier())
    assert "found 2 dependencies" in result.content
    assert pool.dispatch_count == 3


@pytest.mark.anyio
async def test_react_stops_at_max_steps() -> None:
    from ryuu._testing.fakes import FakeAgentPool, FakeVerifier
    from ryuu.execution.agent import AgentResult
    from ryuu.observability.cost import Cost

    # Never sends DONE — should stop at max_steps
    responses = [
        AgentResult(task_id=f"t{i}", output=f"ACTION:step{i}", cost=Cost.zero())
        for i in range(20)
    ]
    pool = FakeAgentPool(responses=responses)
    result = await ReActStrategy(max_steps=4).execute(_intent(), _ctx(), pool, FakeVerifier())
    assert pool.dispatch_count == 4
    assert isinstance(result, CognitiveResult)


@pytest.mark.anyio
async def test_react_accumulates_reasoning() -> None:
    from ryuu._testing.fakes import FakeAgentPool, FakeVerifier
    from ryuu.execution.agent import AgentResult
    from ryuu.observability.cost import Cost

    pool = FakeAgentPool(responses=[
        AgentResult(task_id="t1", output="ACTION:step1", cost=Cost.zero()),
        AgentResult(task_id="t2", output="DONE:final answer", cost=Cost.zero()),
    ])
    result = await ReActStrategy().execute(_intent(), _ctx(), pool, FakeVerifier())
    assert "step1" in result.reasoning
