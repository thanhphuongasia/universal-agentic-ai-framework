"""Unit tests for AnthropicProvider (with mocked anthropic client) — T10."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from uaaf.observability.cost import Cost
from uaaf.providers.adapters.anthropic import AnthropicProvider
from uaaf.providers.llm import CompletionRequest, Message


def _make_request(content: str = "test") -> CompletionRequest:
    return CompletionRequest(
        messages=[Message(role="user", content=content)],
        model="claude-haiku-4-5",
        max_tokens=100,
    )


# ---------------------------------------------------------------------------
# complete()
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_complete_returns_response() -> None:
    with patch("uaaf.providers.adapters.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = mock_cls.return_value
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = "Claude says hi"
        mock_usage = MagicMock()
        mock_usage.input_tokens = 8
        mock_usage.output_tokens = 4
        mock_resp = MagicMock()
        mock_resp.content = [mock_block]
        mock_resp.usage = mock_usage
        mock_resp.stop_reason = "end_turn"
        mock_client.messages.create = AsyncMock(return_value=mock_resp)

        provider = AnthropicProvider(api_key="ak-test")
        response = await provider.complete(_make_request())

    assert response.content == "Claude says hi"
    assert response.usage.input_tokens == 8
    assert response.usage.output_tokens == 4
    assert response.finish_reason == "end_turn"


@pytest.mark.anyio
async def test_complete_maps_rate_limit_to_retryable() -> None:
    from uaaf.observability.errors import RetryableError

    class FakeOverloadedError(Exception):
        __module__ = "anthropic"

    FakeOverloadedError.__name__ = "OverloadedError"

    with patch("uaaf.providers.adapters.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = mock_cls.return_value
        mock_client.messages.create = AsyncMock(side_effect=FakeOverloadedError("overloaded"))

        provider = AnthropicProvider(api_key="ak-test")
        with pytest.raises(RetryableError):
            await provider.complete(_make_request())


@pytest.mark.anyio
async def test_complete_maps_auth_error_to_fatal() -> None:
    from uaaf.observability.errors import FatalError

    class FakeAuthError(Exception):
        __module__ = "anthropic"

    FakeAuthError.__name__ = "AuthenticationError"

    with patch("uaaf.providers.adapters.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = mock_cls.return_value
        mock_client.messages.create = AsyncMock(side_effect=FakeAuthError("bad key"))

        provider = AnthropicProvider(api_key="ak-test")
        with pytest.raises(FatalError):
            await provider.complete(_make_request())


# ---------------------------------------------------------------------------
# embed() — not supported
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_embed_raises_not_implemented() -> None:
    with patch("uaaf.providers.adapters.anthropic.AsyncAnthropic"):
        provider = AnthropicProvider(api_key="ak-test")

    with pytest.raises(NotImplementedError):
        await provider.embed("hello")


# ---------------------------------------------------------------------------
# estimate_cost()
# ---------------------------------------------------------------------------


def test_estimate_cost_returns_cost_object() -> None:
    with patch("uaaf.providers.adapters.anthropic.AsyncAnthropic"):
        provider = AnthropicProvider(api_key="ak-test")

    cost = provider.estimate_cost(_make_request())
    assert isinstance(cost, Cost)
    assert cost.provider == "anthropic"
    assert cost.usd >= 0.0


# ---------------------------------------------------------------------------
# Structured output (tool_use pattern)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_complete_with_schema_uses_tool_result() -> None:
    with patch("uaaf.providers.adapters.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = mock_cls.return_value
        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.name = "structured_output"
        mock_block.input = {"key": "value"}
        mock_usage = MagicMock()
        mock_usage.input_tokens = 5
        mock_usage.output_tokens = 3
        mock_resp = MagicMock()
        mock_resp.content = [mock_block]
        mock_resp.usage = mock_usage
        mock_resp.stop_reason = "tool_use"
        mock_client.messages.create = AsyncMock(return_value=mock_resp)

        provider = AnthropicProvider(api_key="ak-test")
        req = _make_request()
        req.response_schema = {"type": "object", "properties": {"key": {"type": "string"}}}
        response = await provider.complete(req)

    import json

    assert json.loads(response.content) == {"key": "value"}
