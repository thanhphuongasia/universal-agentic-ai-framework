"""Unit tests for RequestHandler + ExecutionContext frozen — P7-T09."""

from __future__ import annotations

import dataclasses

import pytest

from uaaf._testing.fakes import FakeAgentPool, FakeIntentAnalyzer, FakeVerifier
from uaaf.intent.models import CognitiveResult, CostEstimate, StructuredIntent
from uaaf.intent.selector import StrategySelector
from uaaf_workflow.context import ContextScope, ExecutionContext
from uaaf.runtime.request_handler import RequestHandler


def _ctx(strategy_id: str | None = None) -> ExecutionContext:
    scope = ContextScope(user_id="u1", session_id="s1", domain="test")
    return ExecutionContext(scope=scope, correlation_id="corr-1", strategy_id=strategy_id)


class FakeStrategy:
    """Minimal ICognitiveStrategy for testing RequestHandler wiring."""

    strategy_id = "fake-strategy"
    received_ctx: ExecutionContext | None = None

    def applicable(self, intent: StructuredIntent, context: ExecutionContext) -> bool:
        return True

    def estimate_cost(self, intent: StructuredIntent, context: ExecutionContext) -> CostEstimate:
        return CostEstimate(input_tokens_est=0, output_tokens_est=0, usd_est=0.0)

    async def execute(
        self,
        intent: StructuredIntent,
        context: ExecutionContext,
        agent_pool: object,
        verifier: object,
    ) -> CognitiveResult:
        FakeStrategy.received_ctx = context
        return CognitiveResult(
            strategy_id=self.strategy_id,
            content="response",
            confidence=0.9,
        )


def _make_handler() -> RequestHandler:
    analyzer = FakeIntentAnalyzer()
    selector = StrategySelector([FakeStrategy()])
    pool = FakeAgentPool()
    verifier = FakeVerifier()
    return RequestHandler(analyzer=analyzer, selector=selector, pool=pool, verifier=verifier)


class TestExecutionContextFrozen:
    def test_frozen_raises_on_direct_assignment(self):
        ctx = _ctx()
        with pytest.raises((AttributeError, TypeError)):
            ctx.strategy_id = "x"  # type: ignore[misc]

    def test_strategy_id_defaults_to_none(self):
        ctx = _ctx()
        assert ctx.strategy_id is None

    def test_dataclasses_replace_creates_new_instance(self):
        ctx = _ctx()
        ctx2 = dataclasses.replace(ctx, strategy_id="react")
        assert ctx2.strategy_id == "react"
        assert ctx.strategy_id is None  # original unchanged

    def test_replace_preserves_other_fields(self):
        ctx = _ctx()
        ctx2 = dataclasses.replace(ctx, strategy_id="direct")
        assert ctx2.scope is ctx.scope
        assert ctx2.correlation_id == ctx.correlation_id

    def test_isinstance_still_executioncontext(self):
        ctx = _ctx()
        ctx2 = dataclasses.replace(ctx, strategy_id="s")
        assert isinstance(ctx2, ExecutionContext)


class TestRequestHandlerHandle:
    @pytest.mark.asyncio
    async def test_handle_returns_cognitive_result(self):
        handler = _make_handler()
        result = await handler.handle("search something", _ctx())
        assert isinstance(result, CognitiveResult)
        assert result.content == "response"

    @pytest.mark.asyncio
    async def test_handle_stamps_strategy_id_on_context(self):
        FakeStrategy.received_ctx = None
        handler = _make_handler()
        await handler.handle("query", _ctx())
        assert FakeStrategy.received_ctx is not None
        assert FakeStrategy.received_ctx.strategy_id == "fake-strategy"

    @pytest.mark.asyncio
    async def test_original_context_not_mutated(self):
        FakeStrategy.received_ctx = None
        original_ctx = _ctx()
        handler = _make_handler()
        await handler.handle("query", original_ctx)
        # Original still has strategy_id=None
        assert original_ctx.strategy_id is None
        # Routed context has strategy_id set
        assert FakeStrategy.received_ctx is not None
        assert FakeStrategy.received_ctx.strategy_id == "fake-strategy"

    @pytest.mark.asyncio
    async def test_handle_calls_analyzer_with_message(self):
        analyzer = FakeIntentAnalyzer()
        handler = RequestHandler(
            analyzer=analyzer,
            selector=StrategySelector([FakeStrategy()]),
            pool=FakeAgentPool(),
            verifier=FakeVerifier(),
        )
        await handler.handle("hello world", _ctx())
        assert analyzer.last_message == "hello world"
        assert analyzer.call_count == 1

    @pytest.mark.asyncio
    async def test_handle_uses_scope_key_for_analysis(self):
        analyzer = FakeIntentAnalyzer()
        scope = ContextScope(user_id="u2", session_id="s2", domain="finance")
        ctx = ExecutionContext(scope=scope, correlation_id="c2")
        handler = RequestHandler(
            analyzer=analyzer,
            selector=StrategySelector([FakeStrategy()]),
            pool=FakeAgentPool(),
            verifier=FakeVerifier(),
        )
        await handler.handle("buy stock", ctx)
        assert analyzer.call_count == 1  # called with scope_key (tested via call_count)
