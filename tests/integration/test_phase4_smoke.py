"""Phase 4 integration smoke — ModelRouter + CircuitBreaker fallback end-to-end."""

from __future__ import annotations

import pytest

from uaaf._testing.fakes import FakeLLMProvider
from uaaf.intent.models import ModelTier
from uaaf.observability.errors import RetryableError
from uaaf.providers.fallback import ProviderFallbackChain
from uaaf.providers.llm import CompletionRequest, Message, Response, TokenUsage
from uaaf.providers.router import ModelRouter
from uaaf.runtime.context import ContextScope, ExecutionContext


def _resp(text: str) -> Response:
    return Response(content=text, model="fake", usage=TokenUsage(10, 5), finish_reason="stop")


def _req(model: str = "gpt-4o-mini") -> CompletionRequest:
    return CompletionRequest(messages=[Message(role="user", content="test")], model=model)


@pytest.fixture()
def ctx() -> ExecutionContext:
    return ExecutionContext(
        scope=ContextScope(user_id="u1", session_id="s1", domain="test"),
        correlation_id="c1",
    )


class TestModelRouterFallback:
    @pytest.mark.asyncio
    async def test_primary_down_uses_fallback(self):
        primary = FakeLLMProvider(raise_on_call=RetryableError("primary down"))
        fallback = FakeLLMProvider(responses=[_resp("fallback response")])
        router = ModelRouter(
            providers={ModelTier.CHEAP: primary},
            fallback=fallback,
            failure_threshold=1,
        )
        result = await router.complete(_req(model="gpt-4o-mini"))
        assert result.content == "fallback response"

    @pytest.mark.asyncio
    async def test_circuit_opens_then_recovers(self):
        primary = FakeLLMProvider(responses=[_resp("recovered")])
        router = ModelRouter(
            providers={ModelTier.CHEAP: primary},
            failure_threshold=2,
            recovery_timeout=0.05,
        )
        # Trip the circuit manually
        router.record_failure(primary.provider_id)
        router.record_failure(primary.provider_id)
        assert not router._breakers[primary.provider_id].is_available()

        import time
        time.sleep(0.1)

        # After timeout, circuit should allow through
        assert router._breakers[primary.provider_id].is_available()


class TestFallbackChainWithStrategy:
    @pytest.mark.asyncio
    async def test_chain_strategy_end_to_end(self, ctx):
        p1 = FakeLLMProvider(raise_on_call=RetryableError("p1 down"))
        p2 = FakeLLMProvider(responses=[_resp("ok")])
        chain = ProviderFallbackChain(providers=[p1, p2])

        result = await chain.complete(_req())
        assert result.content == "ok"
        assert p2.call_count == 1


class TestModelRouterTierRouting:
    @pytest.mark.asyncio
    async def test_cheap_tier_routes_correctly(self):
        cheap = FakeLLMProvider(responses=[_resp("cheap")])
        powerful = FakeLLMProvider(responses=[_resp("powerful")])
        router = ModelRouter(
            providers={
                ModelTier.CHEAP: cheap,
                ModelTier.POWERFUL: powerful,
            }
        )
        result = await router.complete(_req(model="claude-haiku-4-5"))
        assert result.content == "cheap"
        assert powerful.call_count == 0

    @pytest.mark.asyncio
    async def test_powerful_tier_routes_correctly(self):
        cheap = FakeLLMProvider(responses=[_resp("cheap")])
        powerful = FakeLLMProvider(responses=[_resp("powerful")])
        router = ModelRouter(
            providers={
                ModelTier.CHEAP: cheap,
                ModelTier.POWERFUL: powerful,
            }
        )
        result = await router.complete(_req(model="claude-opus-4"))
        assert result.content == "powerful"
        assert cheap.call_count == 0
