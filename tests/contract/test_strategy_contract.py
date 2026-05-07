"""Contract tests for ICognitiveStrategy — every strategy must pass these — P1-T09.

Parametrized over STRATEGY_REGISTRY. Add entries when adding new strategies.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from uaaf._testing.fakes import FakeAgentPool, FakeVerifier
from uaaf.cognitive.strategy import ICognitiveStrategy
from uaaf.execution.agent import AgentResult
from uaaf.intent.models import (
    CognitiveResult,
    ComplexityLevel,
    CostEstimate,
    StructuredIntent,
)
from uaaf.observability.cost import Cost
from uaaf.runtime.context import ContextScope, ExecutionContext


def _make_direct():
    from uaaf.cognitive.strategies.direct import DirectStrategy
    return DirectStrategy()


def _make_react():
    from uaaf.cognitive.strategies.react import ReActStrategy
    return ReActStrategy()


def _make_evaluator_optimizer():
    from uaaf.cognitive.strategies.evaluator_optimizer import EvaluatorOptimizerStrategy
    return EvaluatorOptimizerStrategy()


STRATEGY_REGISTRY: dict[str, Callable] = {
    "direct": _make_direct,
    "react": _make_react,
    "evaluator_optimizer": _make_evaluator_optimizer,
}


def _high_intent() -> StructuredIntent:
    return StructuredIntent(
        intent_type="analysis",
        action="trace",
        entities={},
        complexity=ComplexityLevel.HIGH,
        confidence=0.9,
    )


def _ctx() -> ExecutionContext:
    return ExecutionContext(
        scope=ContextScope(user_id="u1", session_id="s1", domain="test"),
        correlation_id="c1",
    )


def _pool_with_done() -> FakeAgentPool:
    """Pool that always returns a DONE: response (for ReAct)."""
    return FakeAgentPool(responses=[
        AgentResult(task_id="t1", output="DONE:contract test answer", cost=Cost.zero()),
    ] * 10)


# ---------------------------------------------------------------------------
# Contract: strategy_id is a non-empty string
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,factory", STRATEGY_REGISTRY.items())
def test_strategy_has_strategy_id(name: str, factory: Callable) -> None:
    strategy = factory()
    assert hasattr(strategy, "strategy_id")
    assert isinstance(strategy.strategy_id, str)
    assert len(strategy.strategy_id) > 0


# ---------------------------------------------------------------------------
# Contract: applicable returns bool
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,factory", STRATEGY_REGISTRY.items())
def test_applicable_returns_bool(name: str, factory: Callable) -> None:
    strategy = factory()
    result = strategy.applicable(_high_intent(), _ctx())
    assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# Contract: estimate_cost returns CostEstimate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,factory", STRATEGY_REGISTRY.items())
def test_estimate_cost_returns_cost_estimate(name: str, factory: Callable) -> None:
    strategy = factory()
    cost = strategy.estimate_cost(_high_intent(), _ctx())
    assert isinstance(cost, CostEstimate)
    assert cost.usd_est >= 0.0
    assert cost.steps_est >= 1


# ---------------------------------------------------------------------------
# Contract: execute returns CognitiveResult with content + confidence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,factory", STRATEGY_REGISTRY.items())
@pytest.mark.anyio
async def test_execute_returns_cognitive_result(name: str, factory: Callable) -> None:
    strategy = factory()
    result = await strategy.execute(
        _high_intent(), _ctx(), _pool_with_done(), FakeVerifier()
    )
    assert isinstance(result, CognitiveResult)
    assert isinstance(result.content, str)
    assert isinstance(result.confidence, float)
    assert 0.0 <= result.confidence <= 1.0


# ---------------------------------------------------------------------------
# Contract: execute sets strategy_id on result
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,factory", STRATEGY_REGISTRY.items())
@pytest.mark.anyio
async def test_execute_sets_strategy_id(name: str, factory: Callable) -> None:
    strategy = factory()
    result = await strategy.execute(
        _high_intent(), _ctx(), _pool_with_done(), FakeVerifier()
    )
    assert result.strategy_id == strategy.strategy_id


# ---------------------------------------------------------------------------
# Contract: implements ICognitiveStrategy Protocol
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,factory", STRATEGY_REGISTRY.items())
def test_strategy_satisfies_protocol(name: str, factory: Callable) -> None:
    strategy = factory()
    assert isinstance(strategy, ICognitiveStrategy)
