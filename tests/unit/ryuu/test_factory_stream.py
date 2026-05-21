"""Phase 10.4: `.stream()`, multi-provider fallback, budget_tokens.

12 cases. Expected RED until implementation.
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


# ── Streaming ─────────────────────────────────────────────────────────────


async def test_stream_yields_final_event() -> None:
    """`.stream()` yields at least a 'final' event with output."""
    agent = Agent(model="gpt-4o-mini")
    agent._agent.llm = FakeLLMProvider(responses=[_fake_response("Hello")])  # type: ignore[attr-defined]

    events = [ev async for ev in agent.stream("Hi")]
    assert any(ev.type == "final" for ev in events)
    final = next(ev for ev in events if ev.type == "final")
    assert final.text == "Hello"


async def test_stream_event_type_field() -> None:
    """StreamEvent has `type` field with allowed values."""
    agent = Agent(model="gpt-4o-mini")
    agent._agent.llm = FakeLLMProvider(responses=[_fake_response()])  # type: ignore[attr-defined]

    events = [ev async for ev in agent.stream("Hi")]
    ALLOWED = {"token", "thought", "tool_call", "tool_result", "error", "final"}
    for ev in events:
        assert ev.type in ALLOWED


async def test_stream_with_template_mode2() -> None:
    """`.stream()` supports Mode 2 template kwargs."""
    agent = Agent(
        model="gpt-4o-mini",
        system="Translator.",
        user_template="To VN: {text}",
    )
    agent._agent.llm = FakeLLMProvider(responses=[_fake_response("Xin chào")])  # type: ignore[attr-defined]

    events = [ev async for ev in agent.stream(text="Hello")]
    final = next(ev for ev in events if ev.type == "final")
    assert final.text == "Xin chào"


async def test_stream_scope_kwargs_separated() -> None:
    """Reserved kwargs (user_id) don't flow into template substitution."""
    agent = Agent(model="gpt-4o-mini", user_template="Echo: {msg}")
    agent._agent.llm = FakeLLMProvider(responses=[_fake_response()])  # type: ignore[attr-defined]

    events = [ev async for ev in agent.stream(msg="ok", user_id="u-1")]
    assert any(ev.type == "final" for ev in events)


# ── Multi-provider fallback `model=[list]` ────────────────────────────────


def test_model_list_first_used_when_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    """`model=[a, b]` uses first when first builds successfully."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    agent = Agent(model=["gpt-4o-mini", "claude-sonnet-4"])
    # Primary provider is first in list
    assert "OpenAI" in agent._agent.llm.__class__.__name__  # type: ignore[attr-defined]


def test_model_list_validation_empty_raises() -> None:
    """`model=[]` empty list → ValueError."""
    with pytest.raises(ValueError, match="model"):
        Agent(model=[])


def test_model_list_explicit_prefix() -> None:
    """`model=["openai:gpt-4o", "anthropic:claude-sonnet-4"]` both parsed."""
    import os
    os.environ.setdefault("OPENAI_API_KEY", "sk-test")
    os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")

    agent = Agent(model=["openai:gpt-4o", "anthropic:claude-sonnet-4"])
    # Fallback chain stored for later use
    assert hasattr(agent._agent, "_fallback_providers")  # type: ignore[attr-defined]
    assert len(agent._agent._fallback_providers) == 1  # type: ignore[attr-defined]


def test_model_str_no_fallback_chain() -> None:
    """`model=str` (single) → empty fallback chain."""
    agent = Agent(model="gpt-4o-mini")
    assert agent._agent._fallback_providers == []  # type: ignore[attr-defined]


# ── budget_tokens ─────────────────────────────────────────────────────────


def test_budget_tokens_field_stored() -> None:
    """`budget_tokens=N` stored on internal agent."""
    agent = Agent(model="gpt-4o-mini", budget_tokens=10_000)
    assert getattr(agent._agent, "_budget_tokens", None) == 10_000  # type: ignore[attr-defined]


def test_budget_tokens_default_none() -> None:
    """`budget_tokens` default None (unlimited)."""
    agent = Agent(model="gpt-4o-mini")
    assert getattr(agent._agent, "_budget_tokens", -1) is None  # type: ignore[attr-defined]


def test_budget_tokens_negative_raises() -> None:
    """`budget_tokens <= 0` → ValueError."""
    with pytest.raises(ValueError, match="budget_tokens"):
        Agent(model="gpt-4o-mini", budget_tokens=-1)


def test_budget_tokens_and_budget_usd_both_allowed() -> None:
    """Both budgets can coexist (USD cost cap + token count cap independent)."""
    agent = Agent(model="gpt-4o-mini", budget_usd=1.0, budget_tokens=50_000)
    assert agent.budget_usd == 1.0
    assert agent.budget_tokens == 50_000
