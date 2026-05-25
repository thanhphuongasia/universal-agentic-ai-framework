"""Unit tests for RyuuHandler._run_streaming().

Covers the 5 event-routing cases:
  1. final only         → returns text, on_event never called
  2. thought + final    → on_event called once ("thought", text)
  3. tool_call + tool_result + final → on_event called twice
  4. token + final      → token is ignored, on_event never called
  5. final with text="" → returns placeholder "(no response)"
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest

from examples.ryuu_sensei.apps.ryuu_handler import RyuuHandler, UserSettings
from ryuu.factory.stream_event import StreamEvent
from ryuu_messaging_core import IncomingMessage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")


def _handler() -> RyuuHandler:
    return RyuuHandler(memory_backbone=None)


def _msg() -> IncomingMessage:
    return IncomingMessage(
        channel="telegram",
        sender_id="u-1",
        conversation_id="c-1",
        text="hello",
    )


async def _fake_stream(*events: StreamEvent) -> AsyncGenerator[StreamEvent, None]:
    for e in events:
        yield e


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_run_streaming_returns_final_text() -> None:
    """A single 'final' event → returns that text; on_event is never called."""
    handler = _handler()
    agent = handler._get_agent(handler.get_settings("s"))
    agent.stream = lambda **kwargs: _fake_stream(  # type: ignore[method-assign]
        StreamEvent(type="final", text="Hello world"),
    )

    calls: list[tuple[str, str]] = []

    async def on_event(kind: str, value: str) -> None:
        calls.append((kind, value))

    result = await handler._run_streaming(agent, "hi", _msg(), "s", on_event)

    assert result == "Hello world"
    assert calls == []


async def test_run_streaming_on_event_called_for_thoughts() -> None:
    """A 'thought' event before 'final' → on_event called once; returns final text."""
    handler = _handler()
    agent = handler._get_agent(handler.get_settings("s"))
    agent.stream = lambda **kwargs: _fake_stream(  # type: ignore[method-assign]
        StreamEvent(type="thought", text="I am thinking..."),
        StreamEvent(type="final", text="Done"),
    )

    calls: list[tuple[str, str]] = []

    async def on_event(kind: str, value: str) -> None:
        calls.append((kind, value))

    result = await handler._run_streaming(agent, "hi", _msg(), "s", on_event)

    assert result == "Done"
    assert calls == [("thought", "I am thinking...")]


async def test_run_streaming_on_event_called_for_tool_call() -> None:
    """'tool_call' and 'tool_result' events each fire on_event; 'final' is returned."""
    handler = _handler()
    agent = handler._get_agent(handler.get_settings("s"))
    agent.stream = lambda **kwargs: _fake_stream(  # type: ignore[method-assign]
        StreamEvent(type="tool_call", tool_name="recall"),
        StreamEvent(type="tool_result", result="Memory content here"),
        StreamEvent(type="final", text="Here is my answer"),
    )

    calls: list[tuple[str, str]] = []

    async def on_event(kind: str, value: str) -> None:
        calls.append((kind, value))

    result = await handler._run_streaming(agent, "hi", _msg(), "s", on_event)

    assert result == "Here is my answer"
    assert calls == [
        ("tool_call", "recall"),
        ("tool_result", "Memory content here"),
    ]


async def test_run_streaming_ignores_token_events() -> None:
    """'token' events are silently ignored; on_event is never called."""
    handler = _handler()
    agent = handler._get_agent(handler.get_settings("s"))
    agent.stream = lambda **kwargs: _fake_stream(  # type: ignore[method-assign]
        StreamEvent(type="token", text="chunk"),
        StreamEvent(type="final", text="Complete"),
    )

    calls: list[tuple[str, str]] = []

    async def on_event(kind: str, value: str) -> None:
        calls.append((kind, value))

    result = await handler._run_streaming(agent, "hi", _msg(), "s", on_event)

    assert result == "Complete"
    assert calls == []


async def test_run_streaming_empty_final_returns_placeholder() -> None:
    """A 'final' event with text='' → returns the placeholder '(no response)'."""
    handler = _handler()
    agent = handler._get_agent(handler.get_settings("s"))
    agent.stream = lambda **kwargs: _fake_stream(  # type: ignore[method-assign]
        StreamEvent(type="final", text=""),
    )

    calls: list[tuple[str, str]] = []

    async def on_event(kind: str, value: str) -> None:
        calls.append((kind, value))

    result = await handler._run_streaming(agent, "hi", _msg(), "s", on_event)

    assert result == "(no response)"
    assert calls == []
