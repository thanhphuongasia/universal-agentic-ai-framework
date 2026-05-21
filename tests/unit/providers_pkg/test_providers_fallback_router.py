"""RED tests for ryuu_providers.fallback + ryuu_providers.router — T03."""

from __future__ import annotations

import pytest


def test_fallback_chain_import() -> None:
    from ryuu_providers.fallback import ProviderFallbackChain
    chain = ProviderFallbackChain(providers=[])
    assert chain.provider_id == "fallback_chain"


@pytest.mark.asyncio
async def test_fallback_chain_empty_raises() -> None:
    from ryuu_core.errors import DegradedError
    from ryuu_providers.fallback import ProviderFallbackChain
    from ryuu_providers.llm import CompletionRequest, Message

    chain = ProviderFallbackChain(providers=[])
    req = CompletionRequest(messages=[Message(role="user", content="hi")], model="gpt-4o-mini")
    with pytest.raises(DegradedError):
        await chain.complete(req)


def test_model_router_import() -> None:
    from ryuu_providers.router import ModelRouter
    assert ModelRouter is not None


def test_model_router_no_provider_raises() -> None:
    from ryuu_core.errors import DegradedError
    from ryuu_core.models import ModelTier
    from ryuu_providers.router import ModelRouter

    router = ModelRouter(providers={})
    with pytest.raises(DegradedError):
        router.route(ModelTier.STANDARD)


def test_model_router_routes_to_provider() -> None:
    from unittest.mock import MagicMock

    from ryuu_core.models import ModelTier
    from ryuu_providers.router import ModelRouter

    mock_provider = MagicMock()
    mock_provider.provider_id = "mock"
    router = ModelRouter(providers={ModelTier.STANDARD: mock_provider})
    result = router.route(ModelTier.STANDARD)
    assert result is mock_provider


def test_model_router_tier_from_model_name() -> None:
    from unittest.mock import MagicMock

    from ryuu_core.models import ModelTier
    from ryuu_providers.router import ModelRouter

    mock = MagicMock()
    mock.provider_id = "mock"
    router = ModelRouter(providers={ModelTier.CHEAP: mock})
    # "haiku" → CHEAP tier
    tier = router._model_to_tier("claude-haiku-4-5")
    assert tier == ModelTier.CHEAP
