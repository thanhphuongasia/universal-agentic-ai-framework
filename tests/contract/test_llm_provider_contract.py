"""Contract tests for ILLMProvider — every adapter must pass these — T07.

Tests are parametrized over PROVIDER_REGISTRY.  Add entries when adding new adapters.
"""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from uaaf._testing.fakes import FakeLLMProvider
from uaaf.observability.cost import Cost
from uaaf.providers.llm import CompletionRequest, Message


def _req(model: str = "fake") -> CompletionRequest:
    return CompletionRequest(
        messages=[Message(role="user", content="contract test")],
        model=model,
        max_tokens=50,
    )


# ---------------------------------------------------------------------------
# Factories: return a ready-to-use provider instance
# ---------------------------------------------------------------------------


def _make_fake() -> FakeLLMProvider:
    return FakeLLMProvider(default_content="ok")


def _make_openai() -> object:
    from uaaf.providers.adapters.openai import OpenAIProvider

    with patch("uaaf.providers.adapters.openai.AsyncOpenAI") as mock_cls:
        mock_client = mock_cls.return_value
        mock_choice = MagicMock()
        mock_choice.message.content = "openai response"
        mock_choice.finish_reason = "stop"
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 5
        mock_usage.completion_tokens = 3
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_resp.usage = mock_usage
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
        provider = OpenAIProvider(api_key="sk-test")
        provider._client = mock_client  # ensure mock client is used
        return provider


def _make_anthropic() -> object:
    from uaaf.providers.adapters.anthropic import AnthropicProvider

    with patch("uaaf.providers.adapters.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = mock_cls.return_value
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = "anthropic response"
        mock_usage = MagicMock()
        mock_usage.input_tokens = 5
        mock_usage.output_tokens = 3
        mock_resp = MagicMock()
        mock_resp.content = [mock_block]
        mock_resp.usage = mock_usage
        mock_resp.stop_reason = "end_turn"
        mock_client.messages.create = AsyncMock(return_value=mock_resp)
        provider = AnthropicProvider(api_key="ak-test")
        provider._client = mock_client
        return provider


PROVIDER_REGISTRY: dict[str, Callable[[], object]] = {
    "fake": _make_fake,
    "openai": _make_openai,
    "anthropic": _make_anthropic,
}


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,factory", PROVIDER_REGISTRY.items())
@pytest.mark.anyio
async def test_complete_returns_response_with_content(name: str, factory: Callable[[], object]) -> None:
    provider = factory()
    model = "gpt-4o-mini" if name == "openai" else ("claude-haiku-4-5" if name == "anthropic" else "fake")
    response = await provider.complete(_req(model=model))  # type: ignore[union-attr]
    assert isinstance(response.content, str)
    assert len(response.content) > 0


@pytest.mark.parametrize("name,factory", PROVIDER_REGISTRY.items())
@pytest.mark.anyio
async def test_complete_returns_token_usage(name: str, factory: Callable[[], object]) -> None:
    provider = factory()
    model = "gpt-4o-mini" if name == "openai" else ("claude-haiku-4-5" if name == "anthropic" else "fake")
    response = await provider.complete(_req(model=model))  # type: ignore[union-attr]
    assert response.usage.input_tokens >= 0
    assert response.usage.output_tokens >= 0


@pytest.mark.parametrize("name,factory", PROVIDER_REGISTRY.items())
def test_estimate_cost_returns_cost(name: str, factory: Callable[[], object]) -> None:
    provider = factory()
    model = "gpt-4o-mini" if name == "openai" else ("claude-haiku-4-5" if name == "anthropic" else "fake")
    cost = provider.estimate_cost(_req(model=model))  # type: ignore[union-attr]
    assert isinstance(cost, Cost)
    assert cost.usd >= 0.0
    assert cost.provider == name


@pytest.mark.parametrize("name,factory", PROVIDER_REGISTRY.items())
def test_provider_has_provider_id(name: str, factory: Callable[[], object]) -> None:
    provider = factory()
    assert hasattr(provider, "provider_id")
    assert isinstance(provider.provider_id, str)  # type: ignore[union-attr]
    assert len(provider.provider_id) > 0  # type: ignore[union-attr]
