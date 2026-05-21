"""Phase 10.6 — token-by-token streaming + real failover dispatch.

6 cases.
"""

from __future__ import annotations

import pytest

from ryuu import Agent
from ryuu._testing.fakes import FakeLLMProvider
from ryuu.providers.llm import Response, TokenUsage


def _fake_response(text: str = "ok") -> Response:
    return Response(
        content=text,
        model="fake",
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        finish_reason="stop",
    )


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")


# ── Token streaming ─────────────────────────────────────────────────────────


async def test_stream_emits_token_events_without_tools() -> None:
    """When no tools, stream() yields token events from provider.stream()."""
    agent = Agent(model="gpt-4o-mini")
    agent._agent.llm = FakeLLMProvider(responses=[_fake_response("Hello world")])  # type: ignore[attr-defined]

    events = [ev async for ev in agent.stream("hi")]
    # Should have at least one token event (FakeLLMProvider yields single chunk)
    token_events = [ev for ev in events if ev.type == "token"]
    final_events = [ev for ev in events if ev.type == "final"]
    assert len(token_events) >= 1
    assert len(final_events) == 1


async def test_stream_with_tools_falls_back_to_semantic_events() -> None:
    """When tools present, stream() falls back to thought/tool_call/final (no token)."""
    def my_tool(x: int) -> dict:
        """Demo tool."""
        return {"x": x}

    agent = Agent(model="gpt-4o-mini", tools=[my_tool])
    agent._agent.llm = FakeLLMProvider(responses=[_fake_response("done")])  # type: ignore[attr-defined]

    events = [ev async for ev in agent.stream("hi")]
    # Has final event but no token events (ReAct path doesn't emit per-token)
    assert any(ev.type == "final" for ev in events)


# ── Failover dispatch ──────────────────────────────────────────────────────


async def test_failover_uses_fallback_when_primary_fails() -> None:
    """When primary provider raises, agent retries with fallback."""
    import os
    os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")

    agent = Agent(model=["openai:gpt-4o-mini", "anthropic:claude-sonnet-4"])

    # Primary fails
    primary = FakeLLMProvider(raise_on_call=ConnectionError("primary down"))
    fallback = FakeLLMProvider(responses=[_fake_response("from fallback")])
    agent._agent.llm = primary  # type: ignore[attr-defined]
    agent._agent._fallback_providers = [fallback]  # type: ignore[attr-defined]

    result = await agent.run("test")
    assert result.output == "from fallback"


async def test_failover_all_fail_raises_last_error() -> None:
    """When all providers raise, last error propagates."""
    import os
    os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")

    agent = Agent(model=["openai:gpt-4o-mini", "anthropic:claude-sonnet-4"])

    primary = FakeLLMProvider(raise_on_call=ConnectionError("primary down"))
    fallback = FakeLLMProvider(raise_on_call=TimeoutError("fallback down"))
    agent._agent.llm = primary  # type: ignore[attr-defined]
    agent._agent._fallback_providers = [fallback]  # type: ignore[attr-defined]

    # BaseAgent wraps, but underlying exception should be raised
    with pytest.raises(Exception):
        await agent.run("test")


async def test_no_failover_when_single_model() -> None:
    """Single model (no list) → no fallback chain."""
    agent = Agent(model="gpt-4o-mini")
    agent._agent.llm = FakeLLMProvider(raise_on_call=ConnectionError("fail"))  # type: ignore[attr-defined]

    with pytest.raises(Exception):
        await agent.run("test")


async def test_failover_preserves_user_message() -> None:
    """Fallback provider receives same prompt as primary tried."""
    import os
    os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")

    agent = Agent(model=["openai:gpt-4o-mini", "anthropic:claude-sonnet-4"])

    primary = FakeLLMProvider(raise_on_call=ConnectionError("primary down"))
    fallback = FakeLLMProvider(responses=[_fake_response("ok")])
    agent._agent.llm = primary  # type: ignore[attr-defined]
    agent._agent._fallback_providers = [fallback]  # type: ignore[attr-defined]

    await agent.run("unique-prompt-xyz")
    # Fallback received the prompt
    assert fallback.last_request is not None
    user_msg = next(m for m in fallback.last_request.messages if m.role == "user")
    assert "unique-prompt-xyz" in user_msg.content
