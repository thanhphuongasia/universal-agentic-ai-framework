"""Tests for EvaluatorOptimizerStrategy — P1-T06."""

from __future__ import annotations

import pytest

from uaaf.cognitive.strategies.evaluator_optimizer import EvaluatorOptimizerStrategy
from uaaf.intent.models import (
    EVALUATOR_OPTIMIZER,
    CognitiveResult,
    ComplexityLevel,
    StructuredIntent,
)
from uaaf_workflow.context import ContextScope, ExecutionContext


def _intent(complexity: ComplexityLevel = ComplexityLevel.HIGH) -> StructuredIntent:
    return StructuredIntent(
        intent_type="synthesis",
        action="generate_report",
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


def test_eo_applicable_on_high() -> None:
    assert EvaluatorOptimizerStrategy().applicable(_intent(ComplexityLevel.HIGH), _ctx()) is True


def test_eo_not_applicable_on_medium() -> None:
    assert EvaluatorOptimizerStrategy().applicable(_intent(ComplexityLevel.MEDIUM), _ctx()) is False


def test_eo_not_applicable_on_low() -> None:
    assert EvaluatorOptimizerStrategy().applicable(_intent(ComplexityLevel.LOW), _ctx()) is False


def test_eo_strategy_id() -> None:
    assert EvaluatorOptimizerStrategy().strategy_id == EVALUATOR_OPTIMIZER


# ---------------------------------------------------------------------------
# execute — pass on first attempt
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_eo_returns_on_first_pass() -> None:
    from uaaf._testing.fakes import FakeAgentPool, FakeVerifier
    from uaaf.execution.agent import AgentResult
    from uaaf.observability.cost import Cost

    pool = FakeAgentPool(responses=[
        AgentResult(task_id="t1", output="high quality answer", cost=Cost.zero()),
    ])
    verifier = FakeVerifier(pass_sequence=[True])
    result = await EvaluatorOptimizerStrategy().execute(_intent(), _ctx(), pool, verifier)

    assert isinstance(result, CognitiveResult)
    assert result.content == "high quality answer"
    assert result.strategy_id == EVALUATOR_OPTIMIZER
    assert pool.dispatch_count == 1
    assert verifier.verify_count == 1


@pytest.mark.anyio
async def test_eo_retries_on_fail_then_passes() -> None:
    from uaaf._testing.fakes import FakeAgentPool, FakeVerifier
    from uaaf.execution.agent import AgentResult
    from uaaf.observability.cost import Cost

    pool = FakeAgentPool(responses=[
        AgentResult(task_id="t1", output="draft answer", cost=Cost.zero()),
        AgentResult(task_id="t2", output="refined answer", cost=Cost.zero()),
    ])
    verifier = FakeVerifier(pass_sequence=[False, True])
    result = await EvaluatorOptimizerStrategy().execute(_intent(), _ctx(), pool, verifier)

    assert result.content == "refined answer"
    assert pool.dispatch_count == 2
    assert verifier.verify_count == 2


@pytest.mark.anyio
async def test_eo_returns_best_after_max_rounds() -> None:
    from uaaf._testing.fakes import FakeAgentPool, FakeVerifier
    from uaaf.execution.agent import AgentResult
    from uaaf.observability.cost import Cost

    pool = FakeAgentPool(responses=[
        AgentResult(task_id=f"t{i}", output=f"answer_{i}", cost=Cost.zero())
        for i in range(5)
    ])
    verifier = FakeVerifier(pass_sequence=[False, False, False])  # never passes
    result = await EvaluatorOptimizerStrategy(max_rounds=3).execute(_intent(), _ctx(), pool, verifier)

    assert result.strategy_id == EVALUATOR_OPTIMIZER
    assert pool.dispatch_count == 3


@pytest.mark.anyio
async def test_eo_confidence_from_verifier() -> None:
    from uaaf._testing.fakes import FakeAgentPool, FakeVerifier
    from uaaf.execution.agent import AgentResult
    from uaaf.observability.cost import Cost

    pool = FakeAgentPool(responses=[
        AgentResult(task_id="t1", output="answer", cost=Cost.zero()),
    ])
    verifier = FakeVerifier(pass_sequence=[True], confidence_sequence=[0.95])
    result = await EvaluatorOptimizerStrategy().execute(_intent(), _ctx(), pool, verifier)
    assert result.confidence == 0.95
