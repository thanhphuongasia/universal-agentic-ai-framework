"""Phase 1 end-to-end smoke test: intent → selector → strategy → CognitiveResult — P1-T09."""

from __future__ import annotations

import json

import pytest

from uaaf._testing.fakes import FakeAgentPool, FakeLLMProvider, FakeVerifier
from uaaf.cognitive.strategies.direct import DirectStrategy
from uaaf.cognitive.strategies.evaluator_optimizer import EvaluatorOptimizerStrategy
from uaaf.cognitive.strategies.react import ReActStrategy
from uaaf.execution.agent import AgentResult
from uaaf.intent.llm_analyzer import LLMIntentAnalyzer
from uaaf.intent.models import DIRECT, EVALUATOR_OPTIMIZER, REACT, ComplexityLevel
from uaaf.intent.selector import StrategySelector
from uaaf.observability.cost import Cost
from uaaf.providers.llm import Response, TokenUsage
from uaaf_workflow.context import ContextScope, ExecutionContext


def _ctx() -> ExecutionContext:
    return ExecutionContext(
        scope=ContextScope(user_id="u1", session_id="s1", domain="test"),
        correlation_id="corr-smoke-1",
    )


def _intent_response(complexity: str = "LOW", strategy: str = DIRECT) -> Response:
    payload = json.dumps({
        "intent_type": "query",
        "action": "search",
        "entities": {"term": "UserService"},
        "complexity": complexity,
        "confidence": 0.88,
        "ambiguous": False,
        "clarification_questions": [],
        "suggested_strategy": strategy,
        "suggested_model_tier": "standard",
    })
    return Response(content=payload, model="fake", usage=TokenUsage(10, 5), finish_reason="stop")


# ---------------------------------------------------------------------------
# Smoke: low-complexity request → DirectStrategy
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_phase1_low_complexity_routes_to_direct() -> None:
    intent_provider = FakeLLMProvider(responses=[_intent_response("LOW", DIRECT)])
    analyzer = LLMIntentAnalyzer(provider=intent_provider)

    selector = StrategySelector(strategies=[
        EvaluatorOptimizerStrategy(),
        ReActStrategy(),
        DirectStrategy(),
    ])

    pool = FakeAgentPool(responses=[
        AgentResult(task_id="t1", output="UserService found", cost=Cost.zero()),
    ])
    ctx = _ctx()

    intent = await analyzer.analyze("find UserService", scope_key="u1:s1:test")
    assert intent.complexity == ComplexityLevel.LOW

    strategy = selector.select(intent, ctx)
    assert strategy.strategy_id == DIRECT

    result = await strategy.execute(intent, ctx, pool, FakeVerifier())
    assert "UserService" in result.content
    assert result.strategy_id == DIRECT


# ---------------------------------------------------------------------------
# Smoke: medium complexity → ReActStrategy
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_phase1_medium_complexity_routes_to_react() -> None:
    intent_provider = FakeLLMProvider(responses=[_intent_response("MEDIUM", REACT)])
    analyzer = LLMIntentAnalyzer(provider=intent_provider)

    selector = StrategySelector(strategies=[
        EvaluatorOptimizerStrategy(),
        ReActStrategy(),
        DirectStrategy(),
    ])

    pool = FakeAgentPool(responses=[
        AgentResult(task_id="t1", output="DONE:dependency analysis complete", cost=Cost.zero()),
    ])
    ctx = _ctx()

    intent = await analyzer.analyze("trace dependencies", scope_key="u1:s1:test")
    assert intent.complexity == ComplexityLevel.MEDIUM

    strategy = selector.select(intent, ctx)
    assert strategy.strategy_id == REACT

    result = await strategy.execute(intent, ctx, pool, FakeVerifier())
    assert "dependency analysis complete" in result.content


# ---------------------------------------------------------------------------
# Smoke: high complexity → EvaluatorOptimizerStrategy
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_phase1_high_complexity_routes_to_evaluator_optimizer() -> None:
    intent_provider = FakeLLMProvider(responses=[_intent_response("HIGH", EVALUATOR_OPTIMIZER)])
    analyzer = LLMIntentAnalyzer(provider=intent_provider)

    selector = StrategySelector(strategies=[
        EvaluatorOptimizerStrategy(),
        ReActStrategy(),
        DirectStrategy(),
    ])

    pool = FakeAgentPool(responses=[
        AgentResult(task_id="t1", output="comprehensive analysis report", cost=Cost.zero()),
    ] * 5)
    ctx = _ctx()

    intent = await analyzer.analyze("generate full impact report", scope_key="u1:s1:test")
    assert intent.complexity == ComplexityLevel.HIGH

    strategy = selector.select(intent, ctx)
    assert strategy.strategy_id == EVALUATOR_OPTIMIZER

    result = await strategy.execute(intent, ctx, pool, FakeVerifier(pass_sequence=[True]))
    assert result.strategy_id == EVALUATOR_OPTIMIZER
    assert result.confidence > 0.0


# ---------------------------------------------------------------------------
# Smoke: ambiguous intent → fallback direct
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_phase1_ambiguous_intent_handled() -> None:
    intent_provider = FakeLLMProvider(responses=[
        Response(content="not json", model="fake", usage=TokenUsage(5, 2), finish_reason="stop")
    ])
    analyzer = LLMIntentAnalyzer(provider=intent_provider)
    selector = StrategySelector(strategies=[DirectStrategy()])
    pool = FakeAgentPool()
    ctx = _ctx()

    intent = await analyzer.analyze("???", scope_key="u1:s1:test")
    assert intent.ambiguous is True

    strategy = selector.select(intent, ctx)
    result = await strategy.execute(intent, ctx, pool, FakeVerifier())
    assert isinstance(result.content, str)
