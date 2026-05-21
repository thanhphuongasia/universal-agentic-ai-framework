"""Tests for ryuu.intent.models — P1-T01."""

from __future__ import annotations

import pytest

from ryuu.intent.models import (
    DIRECT,
    EVALUATOR_OPTIMIZER,
    REACT,
    CognitiveResult,
    ComplexityLevel,
    CostEstimate,
    ModelTier,
    StructuredIntent,
)

# ---------------------------------------------------------------------------
# StructuredIntent defaults
# ---------------------------------------------------------------------------


def test_structured_intent_minimal() -> None:
    intent = StructuredIntent(
        intent_type="query",
        action="search",
        entities={},
        complexity=ComplexityLevel.LOW,
        confidence=0.9,
    )
    assert intent.ambiguous is False
    assert intent.clarification_questions == []
    assert intent.suggested_strategy == DIRECT
    assert intent.suggested_model_tier == ModelTier.STANDARD


def test_structured_intent_is_frozen() -> None:
    intent = StructuredIntent(
        intent_type="query",
        action="search",
        entities={},
        complexity=ComplexityLevel.LOW,
        confidence=0.9,
    )
    with pytest.raises((AttributeError, TypeError)):
        intent.confidence = 0.5  # type: ignore[misc]


def test_structured_intent_with_all_fields() -> None:
    intent = StructuredIntent(
        intent_type="analysis",
        action="dependency_analysis",
        entities={"class": "UserService"},
        complexity=ComplexityLevel.HIGH,
        confidence=0.85,
        ambiguous=False,
        clarification_questions=[],
        suggested_strategy=REACT,
        suggested_model_tier=ModelTier.POWERFUL,
    )
    assert intent.entities == {"class": "UserService"}
    assert intent.suggested_strategy == REACT
    assert intent.suggested_model_tier == ModelTier.POWERFUL


def test_structured_intent_ambiguous() -> None:
    intent = StructuredIntent(
        intent_type="unknown",
        action="clarify",
        entities={},
        complexity=ComplexityLevel.LOW,
        confidence=0.3,
        ambiguous=True,
        clarification_questions=["What do you mean?"],
    )
    assert intent.ambiguous is True
    assert len(intent.clarification_questions) == 1


# ---------------------------------------------------------------------------
# ComplexityLevel ordering
# ---------------------------------------------------------------------------


def test_complexity_ordering() -> None:
    assert ComplexityLevel.LOW < ComplexityLevel.MEDIUM < ComplexityLevel.HIGH


def test_complexity_comparison() -> None:
    assert ComplexityLevel.MEDIUM >= ComplexityLevel.MEDIUM
    assert ComplexityLevel.HIGH > ComplexityLevel.LOW


# ---------------------------------------------------------------------------
# StrategyId constants
# ---------------------------------------------------------------------------


def test_strategy_id_constants() -> None:
    assert DIRECT == "direct"
    assert REACT == "react"
    assert EVALUATOR_OPTIMIZER == "evaluator_optimizer"


# ---------------------------------------------------------------------------
# CognitiveResult
# ---------------------------------------------------------------------------


def test_cognitive_result_defaults() -> None:
    result = CognitiveResult(content="answer", confidence=0.9)
    assert result.reasoning == ""
    assert result.evidence == []
    assert result.strategy_id == ""


def test_cognitive_result_is_frozen() -> None:
    result = CognitiveResult(content="x", confidence=1.0)
    with pytest.raises((AttributeError, TypeError)):
        result.content = "y"  # type: ignore[misc]


def test_cognitive_result_with_evidence() -> None:
    result = CognitiveResult(
        content="answer",
        confidence=0.85,
        reasoning="step1 → step2",
        evidence=["fact_a", "fact_b"],
        strategy_id="react",
    )
    assert len(result.evidence) == 2
    assert result.strategy_id == "react"


# ---------------------------------------------------------------------------
# CostEstimate
# ---------------------------------------------------------------------------


def test_cost_estimate_fields() -> None:
    est = CostEstimate(input_tokens_est=500, output_tokens_est=200, usd_est=0.001)
    assert est.steps_est == 1
    assert est.usd_est == 0.001


def test_cost_estimate_multi_step() -> None:
    est = CostEstimate(input_tokens_est=1000, output_tokens_est=500, usd_est=0.01, steps_est=6)
    assert est.steps_est == 6
