"""RED tests for ryuu_core.models — will fail with ImportError until T07."""
import pytest
from ryuu_core.models import (
    AgentResult,
    CognitiveResult,
    ComplexityLevel,
    Cost,
    CostEstimate,
    ModelTier,
    StructuredIntent,
    Task,
)


class TestCost:
    def test_zero(self):
        c = Cost.zero()
        assert c.usd == 0.0
        assert c.input_tokens == 0
        assert c.output_tokens == 0

    def test_zero_custom_provider(self):
        c = Cost.zero(provider="openai", model="gpt-4o")
        assert c.provider == "openai"
        assert c.model == "gpt-4o"

    def test_is_frozen(self):
        c = Cost.zero()
        with pytest.raises((AttributeError, TypeError)):
            c.usd = 1.0  # type: ignore[misc]


class TestTask:
    def test_construction(self):
        t = Task(task_id="t1", payload={"action": "run"})
        assert t.task_id == "t1"
        assert t.estimated_cost is None
        assert t.metadata == {}


class TestAgentResult:
    def test_construction(self):
        cost = Cost.zero()
        r = AgentResult(task_id="t1", output="done", cost=cost)
        assert r.success is True
        assert r.metadata == {}

    def test_failure_result(self):
        r = AgentResult(task_id="t1", output=None, cost=Cost.zero(), success=False)
        assert r.success is False


class TestComplexityLevel:
    def test_ordering(self):
        assert ComplexityLevel.LOW < ComplexityLevel.MEDIUM < ComplexityLevel.HIGH

    def test_values(self):
        assert ComplexityLevel.LOW == 1
        assert ComplexityLevel.HIGH == 3


class TestModelTier:
    def test_values(self):
        assert ModelTier.CHEAP == "cheap"
        assert ModelTier.STANDARD == "standard"
        assert ModelTier.POWERFUL == "powerful"


class TestStructuredIntent:
    def test_construction(self):
        intent = StructuredIntent(
            intent_type="query",
            action="search",
            entities={},
            complexity=ComplexityLevel.LOW,
            confidence=0.9,
        )
        assert intent.ambiguous is False
        assert intent.suggested_model_tier == ModelTier.STANDARD

    def test_is_frozen(self):
        intent = StructuredIntent(
            intent_type="q", action="a", entities={},
            complexity=ComplexityLevel.LOW, confidence=1.0,
        )
        with pytest.raises((AttributeError, TypeError)):
            intent.action = "other"  # type: ignore[misc]


class TestCognitiveResult:
    def test_construction(self):
        r = CognitiveResult(content="answer", confidence=0.8)
        assert r.reasoning == ""
        assert r.evidence == []
        assert r.strategy_id == ""


class TestCostEstimate:
    def test_construction(self):
        est = CostEstimate(input_tokens_est=100, output_tokens_est=50, usd_est=0.01)
        assert est.steps_est == 1
