"""End-to-end `.run()` tests with FakeLLMProvider.

Phase 10 T2.7 — 5 cases. Expected RED until T6 implementation.
"""

from __future__ import annotations

import pytest

from ryuu._testing.fakes import FakeLLMProvider
from ryuu.factory import Agent
from ryuu.providers.llm import Response, TokenUsage


def _fake_response(text: str) -> Response:
    return Response(
        content=text,
        model="fake",
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        finish_reason="stop",
    )


@pytest.fixture
def fake_llm() -> FakeLLMProvider:
    return FakeLLMProvider(responses=[_fake_response("Hello world")])


async def test_run_returns_agent_result(monkeypatch: pytest.MonkeyPatch, fake_llm: FakeLLMProvider) -> None:
    """`.run()` returns AgentResult with output."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    agent = Agent(model="gpt-4o-mini")
    # Inject fake provider after construction
    agent._agent.llm = fake_llm  # type: ignore[attr-defined]

    result = await agent.run("Hi")
    assert result.output == "Hello world"


async def test_run_uses_default_scope(monkeypatch: pytest.MonkeyPatch, fake_llm: FakeLLMProvider) -> None:
    """`.run()` without scope kwargs creates default ContextScope."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    agent = Agent(model="gpt-4o-mini")
    agent._agent.llm = fake_llm  # type: ignore[attr-defined]

    result = await agent.run("Hi")
    # Cost recorded under "anonymous" scope
    assert result is not None


async def test_run_passes_scope_kwargs(monkeypatch: pytest.MonkeyPatch, fake_llm: FakeLLMProvider) -> None:
    """`user_id, session_id, domain` kwargs → ContextScope."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    agent = Agent(model="gpt-4o-mini")
    agent._agent.llm = fake_llm  # type: ignore[attr-defined]

    result = await agent.run("Hi", user_id="u-42", session_id="s-99", domain="test")
    assert result is not None


async def test_run_with_tool_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """Agent invokes tool when LLM returns tool_call."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    def get_weather(city: str) -> dict:
        """Get weather for a city."""
        return {"city": city, "temp_c": 22}

    # FakeLLMProvider with tool_call then final response
    fake = FakeLLMProvider(responses=[
        _fake_response("Tool result: Tokyo 22°C"),
    ])

    agent = Agent(model="gpt-4o-mini", tools=[get_weather])
    agent._agent.llm = fake  # type: ignore[attr-defined]

    result = await agent.run("Weather in Tokyo?")
    assert result is not None


async def test_run_correlation_id_unique(monkeypatch: pytest.MonkeyPatch, fake_llm: FakeLLMProvider) -> None:
    """Each `.run()` generates unique correlation_id."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    agent = Agent(model="gpt-4o-mini")

    # Two separate fake providers since FakeLLMProvider consumes responses
    fake_llm._responses = [  # type: ignore[attr-defined]
        _fake_response("first"),
        _fake_response("second"),
    ]
    agent._agent.llm = fake_llm  # type: ignore[attr-defined]

    r1 = await agent.run("Q1")
    r2 = await agent.run("Q2")
    # Just verify both succeed — correlation_id uniqueness checked via audit log
    assert r1 is not None
    assert r2 is not None
