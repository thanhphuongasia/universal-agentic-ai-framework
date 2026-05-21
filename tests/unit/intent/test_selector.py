"""Tests for ryuu.intent.selector — P1-T03."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from ryuu.cognitive.strategy import IAgentPool, IVerifier
from ryuu.intent.models import (
    DIRECT,
    REACT,
    CognitiveResult,
    ComplexityLevel,
    CostEstimate,
    StructuredIntent,
)
from ryuu.intent.selector import StrategySelector
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


@dataclass
class _AlwaysStrategy:
    strategy_id: str = DIRECT

    def applicable(self, intent: StructuredIntent, context: ExecutionContext) -> bool:
        return True

    def estimate_cost(self, intent: StructuredIntent, context: ExecutionContext) -> CostEstimate:
        return CostEstimate(input_tokens_est=100, output_tokens_est=50, usd_est=0.0)

    async def execute(self, intent: StructuredIntent, context: ExecutionContext, agent_pool: IAgentPool, verifier: IVerifier) -> CognitiveResult:
        return CognitiveResult(content="ok", confidence=1.0)


@dataclass
class _NeverStrategy:
    strategy_id: str = REACT

    def applicable(self, intent: StructuredIntent, context: ExecutionContext) -> bool:
        return False

    def estimate_cost(self, intent: StructuredIntent, context: ExecutionContext) -> CostEstimate:
        return CostEstimate(input_tokens_est=100, output_tokens_est=50, usd_est=0.0)

    async def execute(self, intent: StructuredIntent, context: ExecutionContext, agent_pool: IAgentPool, verifier: IVerifier) -> CognitiveResult:
        return CognitiveResult(content="never", confidence=1.0)


@dataclass
class _ComplexityStrategy:
    min_complexity: ComplexityLevel
    strategy_id: str = "complex"

    def applicable(self, intent: StructuredIntent, context: ExecutionContext) -> bool:
        return intent.complexity >= self.min_complexity

    def estimate_cost(self, intent: StructuredIntent, context: ExecutionContext) -> CostEstimate:
        return CostEstimate(input_tokens_est=500, output_tokens_est=200, usd_est=0.001)

    async def execute(self, intent: StructuredIntent, context: ExecutionContext, agent_pool: IAgentPool, verifier: IVerifier) -> CognitiveResult:
        return CognitiveResult(content="complex", confidence=0.9)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_selector_returns_first_applicable() -> None:
    selector = StrategySelector(strategies=[_NeverStrategy(), _AlwaysStrategy()])
    chosen = selector.select(_intent(), _ctx())
    assert chosen.strategy_id == DIRECT


def test_selector_skips_non_applicable() -> None:
    selector = StrategySelector(strategies=[_NeverStrategy(), _AlwaysStrategy()])
    chosen = selector.select(_intent(), _ctx())
    assert chosen.strategy_id != REACT


def test_selector_first_match_wins() -> None:
    high_strategy = _ComplexityStrategy(min_complexity=ComplexityLevel.HIGH, strategy_id="high")
    med_strategy = _ComplexityStrategy(min_complexity=ComplexityLevel.MEDIUM, strategy_id="med")
    fallback = _AlwaysStrategy(strategy_id="fallback")
    selector = StrategySelector(strategies=[high_strategy, med_strategy, fallback])

    # HIGH complexity → high_strategy is first match
    chosen = selector.select(_intent(ComplexityLevel.HIGH), _ctx())
    assert chosen.strategy_id == "high"

    # MEDIUM complexity → med_strategy is first match (high not applicable)
    chosen = selector.select(_intent(ComplexityLevel.MEDIUM), _ctx())
    assert chosen.strategy_id == "med"

    # LOW complexity → fallback only
    chosen = selector.select(_intent(ComplexityLevel.LOW), _ctx())
    assert chosen.strategy_id == "fallback"


def test_selector_raises_when_no_match() -> None:
    selector = StrategySelector(strategies=[_NeverStrategy()])
    with pytest.raises(ValueError, match="No applicable strategy"):
        selector.select(_intent(), _ctx())


def test_selector_empty_strategies_raises() -> None:
    selector = StrategySelector(strategies=[])
    with pytest.raises(ValueError):
        selector.select(_intent(), _ctx())


def test_selector_single_strategy() -> None:
    selector = StrategySelector(strategies=[_AlwaysStrategy()])
    chosen = selector.select(_intent(), _ctx())
    assert chosen.strategy_id == DIRECT
