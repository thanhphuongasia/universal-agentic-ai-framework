"""Unit tests for ModelRouter — P4-T02+T03."""

from __future__ import annotations

import pytest

from ryuu._testing.fakes import FakeLLMProvider
from ryuu.intent.models import ModelTier
from ryuu_workflow.errors import DegradedError
from ryuu.providers.llm import CompletionRequest, Message, Response, TokenUsage
from ryuu.providers.router import ModelRouter


def _resp(text: str = "ok") -> Response:
    return Response(content=text, model="fake", usage=TokenUsage(10, 5), finish_reason="stop")


def _req(model: str = "gpt-4o-mini") -> CompletionRequest:
    return CompletionRequest(messages=[Message(role="user", content="hi")], model=model)


class TestModelRouterRouting:
    @pytest.mark.asyncio
    async def test_routes_to_cheap_provider(self):
        cheap = FakeLLMProvider(responses=[_resp("cheap answer")])
        standard = FakeLLMProvider(responses=[_resp("standard answer")])
        router = ModelRouter(providers={ModelTier.CHEAP: cheap, ModelTier.STANDARD: standard})
        result = await router.complete(_req(model="gpt-4o-mini"))
        assert result.content == "cheap answer"
        assert cheap.call_count == 1
        assert standard.call_count == 0

    @pytest.mark.asyncio
    async def test_routes_to_standard_provider(self):
        cheap = FakeLLMProvider(responses=[_resp()])
        standard = FakeLLMProvider(responses=[_resp("standard")])
        router = ModelRouter(providers={ModelTier.CHEAP: cheap, ModelTier.STANDARD: standard})
        result = await router.complete(_req(model="gpt-4o"))
        assert result.content == "standard"

    @pytest.mark.asyncio
    async def test_routes_to_powerful_provider(self):
        powerful = FakeLLMProvider(responses=[_resp("powerful")])
        router = ModelRouter(providers={ModelTier.POWERFUL: powerful})
        result = await router.complete(_req(model="claude-opus-4"))
        assert result.content == "powerful"

    @pytest.mark.asyncio
    async def test_fallback_when_tier_missing(self):
        fallback = FakeLLMProvider(responses=[_resp("fallback")])
        router = ModelRouter(providers={}, fallback=fallback)
        result = await router.complete(_req(model="unknown-model"))
        assert result.content == "fallback"

    @pytest.mark.asyncio
    async def test_raises_degraded_when_no_fallback(self):
        router = ModelRouter(providers={})
        with pytest.raises(DegradedError):
            await router.complete(_req(model="unknown-model"))


class TestModelRouterCircuitBreaker:
    @pytest.mark.asyncio
    async def test_falls_back_when_circuit_open(self):
        from ryuu.providers.router import ModelRouter
        cheap = FakeLLMProvider(raise_on_call=Exception("provider down"))
        fallback = FakeLLMProvider(responses=[_resp("fallback ok")])
        router = ModelRouter(
            providers={ModelTier.CHEAP: cheap},
            fallback=fallback,
            failure_threshold=1,
        )
        # First call triggers failure → circuit opens → fallback used
        result = await router.complete(_req(model="gpt-4o-mini"))
        assert result.content == "fallback ok"

    def test_record_failure_updates_breaker(self):
        cheap = FakeLLMProvider(responses=[_resp()])
        router = ModelRouter(providers={ModelTier.CHEAP: cheap}, failure_threshold=1)
        router.record_failure(cheap.provider_id)
        assert not router._breakers[cheap.provider_id].is_available()


class TestModelToTier:
    def test_mini_is_cheap(self):
        router = ModelRouter(providers={})
        assert router._model_to_tier("gpt-4o-mini") == ModelTier.CHEAP

    def test_haiku_is_cheap(self):
        router = ModelRouter(providers={})
        assert router._model_to_tier("claude-haiku-4-5") == ModelTier.CHEAP

    def test_opus_is_powerful(self):
        router = ModelRouter(providers={})
        assert router._model_to_tier("claude-opus-4") == ModelTier.POWERFUL

    def test_default_is_standard(self):
        router = ModelRouter(providers={})
        assert router._model_to_tier("gpt-4o") == ModelTier.STANDARD

    def test_provider_id(self):
        router = ModelRouter(providers={})
        assert router.provider_id == "router"
