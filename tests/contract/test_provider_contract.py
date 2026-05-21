"""Contract tests — ModelRouter + ProviderFallbackChain implement ILLMProvider."""

from __future__ import annotations

import pytest

from ryuu._testing.fakes import FakeLLMProvider
from ryuu.intent.models import ModelTier
from ryuu.observability.cost import Cost
from ryuu.providers.fallback import ProviderFallbackChain
from ryuu.providers.llm import CompletionRequest, ILLMProvider, Message, Response, TokenUsage
from ryuu.providers.router import ModelRouter


def _resp(text: str = "ok") -> Response:
    return Response(content=text, model="fake", usage=TokenUsage(10, 5), finish_reason="stop")


def _req(model: str = "gpt-4o") -> CompletionRequest:
    return CompletionRequest(messages=[Message(role="user", content="hi")], model=model)


@pytest.fixture(
    params=[
        pytest.param("router", id="model_router"),
        pytest.param("fallback", id="fallback_chain"),
    ]
)
def provider(request: pytest.FixtureRequest) -> ILLMProvider:
    fake = FakeLLMProvider(responses=[_resp()] * 5)
    if request.param == "router":
        return ModelRouter(providers={ModelTier.STANDARD: fake})
    return ProviderFallbackChain(providers=[fake])


class TestILLMProviderContract:
    def test_has_provider_id(self, provider: ILLMProvider):
        assert isinstance(provider.provider_id, str)
        assert provider.provider_id != ""

    def test_is_illmprovider(self, provider: ILLMProvider):
        assert isinstance(provider, ILLMProvider)

    @pytest.mark.asyncio
    async def test_complete_returns_response(self, provider: ILLMProvider):
        result = await provider.complete(_req())
        assert isinstance(result, Response)
        assert isinstance(result.content, str)

    def test_estimate_cost_returns_cost(self, provider: ILLMProvider):
        cost = provider.estimate_cost(_req())
        assert isinstance(cost, Cost)
        assert cost.usd >= 0.0
