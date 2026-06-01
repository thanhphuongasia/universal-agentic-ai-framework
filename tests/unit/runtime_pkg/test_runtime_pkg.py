"""Smoke tests for the standalone ryuu_runtime package."""
import pytest
from ryuu_core.context import ContextScope, ExecutionContext
from ryuu_core.models import (
    DIRECT,
    ComplexityLevel,
    CognitiveResult,
    CostEstimate,
    ModelTier,
    StructuredIntent,
)


def test_iintent_analyzer_importable() -> None:
    from ryuu_runtime.analyzer import IIntentAnalyzer  # noqa: F401


def test_llm_intent_analyzer_importable() -> None:
    from ryuu_runtime.llm_analyzer import LLMIntentAnalyzer, INTENT_SYSTEM_PROMPT  # noqa: F401


def test_strategy_selector_importable() -> None:
    from ryuu_runtime.selector import StrategySelector  # noqa: F401


def test_request_handler_importable() -> None:
    from ryuu_runtime.request_handler import RequestHandler  # noqa: F401


def test_top_level_init_importable() -> None:
    from ryuu_runtime import (  # noqa: F401
        IIntentAnalyzer,
        LLMIntentAnalyzer,
        RequestHandler,
        StrategySelector,
    )


def _make_intent(complexity: ComplexityLevel = ComplexityLevel.LOW) -> StructuredIntent:
    return StructuredIntent(
        intent_type="query",
        action="search",
        entities={},
        complexity=complexity,
        confidence=0.9,
        ambiguous=False,
        clarification_questions=[],
        suggested_strategy=DIRECT,
        suggested_model_tier=ModelTier.STANDARD,
    )


def test_strategy_selector_picks_first_applicable() -> None:
    from ryuu_runtime.selector import StrategySelector
    from ryuu_cognitive.strategies import DirectStrategy

    selector = StrategySelector(strategies=[DirectStrategy()])
    ctx = ExecutionContext(
        scope=ContextScope(user_id="u", session_id="s", domain="d"),
        correlation_id="cid",
    )
    intent = _make_intent()
    strategy = selector.select(intent, ctx)
    assert strategy.strategy_id == DIRECT


def test_strategy_selector_raises_when_no_match() -> None:
    from ryuu_runtime.selector import StrategySelector
    from ryuu_cognitive.strategies import EvaluatorOptimizerStrategy

    # EvaluatorOptimizer only applies to HIGH complexity
    selector = StrategySelector(strategies=[EvaluatorOptimizerStrategy()])
    ctx = ExecutionContext(
        scope=ContextScope(user_id="u", session_id="s", domain="d"),
        correlation_id="cid",
    )
    intent = _make_intent(ComplexityLevel.LOW)
    with pytest.raises(ValueError, match="No applicable strategy"):
        selector.select(intent, ctx)


async def test_request_handler_routes_and_returns() -> None:
    from ryuu_runtime.request_handler import RequestHandler
    from ryuu_runtime.selector import StrategySelector
    from ryuu_runtime.analyzer import IIntentAnalyzer
    from ryuu_cognitive.strategies import DirectStrategy
    from ryuu_cognitive.verifier import IVerifier, VerificationResult
    from ryuu_core.models import AgentResult, Cost, Task
    from ryuu_execution.agent import BaseAgent
    from ryuu_execution.pool import AgentPool

    class FakeAnalyzer:
        async def analyze(self, message: str, scope_key: str, history=None) -> StructuredIntent:
            return _make_intent()

    class FakeVerifier:
        verifier_id = "fake"
        async def verify(self, output, context, metadata=None) -> VerificationResult:
            return VerificationResult(passed=True, confidence=1.0)

    class EchoAgent(BaseAgent):
        async def _execute(self, task: Task, context: ExecutionContext) -> AgentResult:
            return AgentResult(
                task_id=task.task_id,
                output="echo result",
                cost=Cost.zero(),
                success=True,
            )

    pool = AgentPool()
    pool.register(EchoAgent(agent_id="echo"))

    handler = RequestHandler(
        analyzer=FakeAnalyzer(),
        selector=StrategySelector([DirectStrategy()]),
        pool=pool,
        verifier=FakeVerifier(),
    )

    ctx = ExecutionContext(
        scope=ContextScope(user_id="u", session_id="s", domain="d"),
        correlation_id="cid",
    )
    result = await handler.handle("hello", ctx)
    assert isinstance(result, CognitiveResult)
    assert result.strategy_id == DIRECT


def test_extract_json_handles_plain_json() -> None:
    from ryuu_intent.llm_analyzer import _extract_json

    data = _extract_json('{"intent_type": "query", "action": "search"}')
    assert data is not None
    assert data["intent_type"] == "query"


def test_extract_json_handles_markdown_block() -> None:
    from ryuu_intent.llm_analyzer import _extract_json

    text = '```json\n{"intent_type": "command"}\n```'
    data = _extract_json(text)
    assert data is not None
    assert data["intent_type"] == "command"


def test_extract_json_returns_none_for_garbage() -> None:
    from ryuu_intent.llm_analyzer import _extract_json

    assert _extract_json("no json here at all") is None
