"""Unit tests for ProviderFallbackChain — P4-T04."""

from __future__ import annotations

import pytest

from ryuu._testing.fakes import FakeLLMProvider
from ryuu_workflow.errors import DegradedError, RetryableError
from ryuu.providers.fallback import ProviderFallbackChain
from ryuu.providers.llm import CompletionRequest, Message, Response, TokenUsage


def _resp(text: str = "ok") -> Response:
    return Response(content=text, model="fake", usage=TokenUsage(10, 5), finish_reason="stop")


def _req() -> CompletionRequest:
    return CompletionRequest(messages=[Message(role="user", content="hi")], model="gpt-4o")


class TestProviderFallbackChain:
    @pytest.mark.asyncio
    async def test_uses_first_available_provider(self):
        p1 = FakeLLMProvider(responses=[_resp("first")])
        p2 = FakeLLMProvider(responses=[_resp("second")])
        chain = ProviderFallbackChain(providers=[p1, p2])
        result = await chain.complete(_req())
        assert result.content == "first"
        assert p2.call_count == 0

    @pytest.mark.asyncio
    async def test_falls_back_on_retryable_error(self):
        p1 = FakeLLMProvider(raise_on_call=RetryableError("p1 down"))
        p2 = FakeLLMProvider(responses=[_resp("from p2")])
        chain = ProviderFallbackChain(providers=[p1, p2])
        result = await chain.complete(_req())
        assert result.content == "from p2"

    @pytest.mark.asyncio
    async def test_falls_back_on_degraded_error(self):
        p1 = FakeLLMProvider(raise_on_call=DegradedError("p1 degraded"))
        p2 = FakeLLMProvider(responses=[_resp("from p2")])
        chain = ProviderFallbackChain(providers=[p1, p2])
        result = await chain.complete(_req())
        assert result.content == "from p2"

    @pytest.mark.asyncio
    async def test_raises_degraded_when_all_fail(self):
        p1 = FakeLLMProvider(raise_on_call=RetryableError("p1"))
        p2 = FakeLLMProvider(raise_on_call=RetryableError("p2"))
        chain = ProviderFallbackChain(providers=[p1, p2])
        with pytest.raises(DegradedError, match="All providers failed"):
            await chain.complete(_req())

    @pytest.mark.asyncio
    async def test_raises_degraded_on_empty_chain(self):
        chain = ProviderFallbackChain(providers=[])
        with pytest.raises(DegradedError):
            await chain.complete(_req())

    def test_estimate_cost_uses_first_provider(self):
        p1 = FakeLLMProvider(responses=[_resp()])
        p2 = FakeLLMProvider(responses=[_resp()])
        chain = ProviderFallbackChain(providers=[p1, p2])
        cost = chain.estimate_cost(_req())
        assert cost is not None

    def test_provider_id(self):
        chain = ProviderFallbackChain(providers=[])
        assert chain.provider_id == "fallback_chain"
