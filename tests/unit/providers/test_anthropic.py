"""Unit tests for AnthropicProvider (with mocked anthropic client) — T10."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ryuu.observability.cost import Cost
from ryuu.providers.adapters.anthropic import AnthropicProvider
from ryuu.providers.llm import CompletionRequest, Message


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
    with patch("ryuu_providers_anthropic.provider.AsyncAnthropic") as mock_cls:
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
    from ryuu_workflow.errors import RetryableError

    class FakeOverloadedError(Exception):
        __module__ = "anthropic"

    FakeOverloadedError.__name__ = "OverloadedError"

    with patch("ryuu_providers_anthropic.provider.AsyncAnthropic") as mock_cls:
        mock_client = mock_cls.return_value
        mock_client.messages.create = AsyncMock(side_effect=FakeOverloadedError("overloaded"))

        provider = AnthropicProvider(api_key="ak-test")
        with pytest.raises(RetryableError):
            await provider.complete(_make_request())


@pytest.mark.anyio
async def test_complete_maps_auth_error_to_fatal() -> None:
    from ryuu_workflow.errors import FatalError

    class FakeAuthError(Exception):
        __module__ = "anthropic"

    FakeAuthError.__name__ = "AuthenticationError"

    with patch("ryuu_providers_anthropic.provider.AsyncAnthropic") as mock_cls:
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
    with patch("ryuu_providers_anthropic.provider.AsyncAnthropic"):
        provider = AnthropicProvider(api_key="ak-test")

    with pytest.raises(NotImplementedError):
        await provider.embed("hello")


# ---------------------------------------------------------------------------
# estimate_cost()
# ---------------------------------------------------------------------------


def test_estimate_cost_returns_cost_object() -> None:
    with patch("ryuu_providers_anthropic.provider.AsyncAnthropic"):
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
    with patch("ryuu_providers_anthropic.provider.AsyncAnthropic") as mock_cls:
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


# ---------------------------------------------------------------------------
# OpenAI-wire → Anthropic translation (2026-07-11: agent react-loop support)
# ---------------------------------------------------------------------------

from ryuu_providers_anthropic.provider import (  # noqa: E402
    _to_anthropic_messages,
    _to_anthropic_tools,
)


def test_system_role_messages_hoisted_to_system_param() -> None:
    msgs = [
        Message(role="system", content="You are helpful."),
        Message(role="user", content="hi"),
    ]
    out, system = _to_anthropic_messages(msgs, None)
    assert system == "You are helpful."
    assert out == [{"role": "user", "content": "hi"}]


def test_request_system_and_system_message_concatenate() -> None:
    msgs = [Message(role="system", content="B"), Message(role="user", content="hi")]
    _, system = _to_anthropic_messages(msgs, "A")
    assert system == "A\n\nB"


def test_assistant_tool_calls_become_tool_use_blocks() -> None:
    msgs = [
        Message(role="user", content="q"),
        Message(role="assistant", content="thinking...", tool_calls=[
            {"id": "t1", "function": {"name": "lookup", "arguments": '{"x": 1}'}},
        ]),
        Message(role="tool", content="result-1", tool_call_id="t1"),
        Message(role="tool", content="result-2", tool_call_id="t2"),
    ]
    out, _ = _to_anthropic_messages(msgs, None)
    assert out[1]["content"][0] == {"type": "text", "text": "thinking..."}
    assert out[1]["content"][1] == {
        "type": "tool_use", "id": "t1", "name": "lookup", "input": {"x": 1},
    }
    # both tool results merged into ONE user message
    assert out[2]["role"] == "user"
    assert [b["tool_use_id"] for b in out[2]["content"]] == ["t1", "t2"]
    assert len(out) == 3


def test_openai_tool_schema_translated() -> None:
    openai_tool = {"type": "function", "function": {
        "name": "f", "description": "d",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }}
    anthropic_native = {"name": "g", "description": "", "input_schema": {"type": "object"}}
    out = _to_anthropic_tools([openai_tool, anthropic_native])
    assert out[0] == {"name": "f", "description": "d",
                      "input_schema": {"type": "object", "properties": {}, "required": []}}
    assert out[1] is anthropic_native


@pytest.mark.anyio
async def test_temperature_rejected_retries_without() -> None:
    # Claude 5 family 400s on `temperature`; provider must retry without it.
    with patch("ryuu_providers_anthropic.provider.AsyncAnthropic") as mock_cls:
        mock_client = mock_cls.return_value
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = "ok"
        mock_usage = MagicMock()
        mock_usage.input_tokens = 1
        mock_usage.output_tokens = 1
        mock_resp = MagicMock()
        mock_resp.content = [mock_block]
        mock_resp.usage = mock_usage
        mock_resp.stop_reason = "end_turn"

        calls: list[dict] = []

        async def create(**kwargs):
            calls.append(kwargs)
            if "temperature" in kwargs:
                raise Exception("`temperature` is deprecated for this model.")
            return mock_resp

        mock_client.messages.create = create
        provider = AnthropicProvider(api_key="ak-test")
        response = await provider.complete(_make_request())

    assert response.content == "ok"
    assert "temperature" in calls[0] and "temperature" not in calls[1]
