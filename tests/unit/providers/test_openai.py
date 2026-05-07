"""Unit tests for OpenAIProvider (with mocked openai client) — T09."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from uaaf.observability.cost import Cost
from uaaf.providers.adapters.openai import OpenAIProvider
from uaaf.providers.llm import CompletionRequest, Message


def _make_provider() -> OpenAIProvider:
    with patch("uaaf.providers.adapters.openai.AsyncOpenAI", autospec=True):
        provider = OpenAIProvider(api_key="sk-test")
    return provider


def _make_request(content: str = "test", model: str = "gpt-4o-mini") -> CompletionRequest:
    return CompletionRequest(
        messages=[Message(role="user", content=content)],
        model=model,
        max_tokens=100,
    )


# ---------------------------------------------------------------------------
# complete()
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_complete_returns_response() -> None:
    from unittest.mock import MagicMock

    with patch("uaaf.providers.adapters.openai.AsyncOpenAI") as mock_cls:
        mock_client = mock_cls.return_value
        mock_choice = MagicMock()
        mock_choice.message.content = "AI response"
        mock_choice.finish_reason = "stop"
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 10
        mock_usage.completion_tokens = 5
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_resp.usage = mock_usage
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        provider = OpenAIProvider(api_key="sk-test")
        response = await provider.complete(_make_request())

    assert response.content == "AI response"
    assert response.usage.input_tokens == 10
    assert response.usage.output_tokens == 5
    assert response.finish_reason == "stop"


@pytest.mark.anyio
async def test_complete_maps_rate_limit_to_retryable() -> None:
    from uaaf.observability.errors import RetryableError

    class FakeRateLimitError(Exception):
        __module__ = "openai"

    FakeRateLimitError.__name__ = "RateLimitError"

    with patch("uaaf.providers.adapters.openai.AsyncOpenAI") as mock_cls:
        mock_client = mock_cls.return_value
        mock_client.chat.completions.create = AsyncMock(side_effect=FakeRateLimitError("limit"))

        provider = OpenAIProvider(api_key="sk-test")
        with pytest.raises(RetryableError):
            await provider.complete(_make_request())


@pytest.mark.anyio
async def test_complete_maps_auth_error_to_fatal() -> None:
    from uaaf.observability.errors import FatalError

    class FakeAuthError(Exception):
        __module__ = "openai"

    FakeAuthError.__name__ = "AuthenticationError"

    with patch("uaaf.providers.adapters.openai.AsyncOpenAI") as mock_cls:
        mock_client = mock_cls.return_value
        mock_client.chat.completions.create = AsyncMock(side_effect=FakeAuthError("bad key"))

        provider = OpenAIProvider(api_key="sk-test")
        with pytest.raises(FatalError):
            await provider.complete(_make_request())


# ---------------------------------------------------------------------------
# estimate_cost()
# ---------------------------------------------------------------------------


def test_estimate_cost_returns_cost_object() -> None:
    with patch("uaaf.providers.adapters.openai.AsyncOpenAI"):
        provider = OpenAIProvider(api_key="sk-test")

    cost = provider.estimate_cost(_make_request())
    assert isinstance(cost, Cost)
    assert cost.provider == "openai"
    assert cost.model == "gpt-4o-mini"
    assert cost.usd >= 0.0
    assert cost.input_tokens > 0
    assert cost.output_tokens > 0


# ---------------------------------------------------------------------------
# embed()
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_embed_returns_embedding() -> None:
    with patch("uaaf.providers.adapters.openai.AsyncOpenAI") as mock_cls:
        mock_client = mock_cls.return_value
        mock_embed_data = MagicMock()
        mock_embed_data.embedding = [0.1, 0.2, 0.3]
        mock_resp = MagicMock()
        mock_resp.data = [mock_embed_data]
        mock_client.embeddings.create = AsyncMock(return_value=mock_resp)

        provider = OpenAIProvider(api_key="sk-test")
        emb = await provider.embed("hello world")

    assert emb.vector == [0.1, 0.2, 0.3]
    assert emb.model == "text-embedding-3-small"
