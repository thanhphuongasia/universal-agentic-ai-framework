"""Provider auto-detect from model string.

Phase 10 T2.3 — 6 cases. Expected RED until T3 implementation.
"""

from __future__ import annotations

import pytest

from ryuu.factory import Agent


def test_detect_openai_from_gpt_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """`gpt-4o` → OpenAIProvider."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    agent = Agent(model="gpt-4o-mini")
    # Provider class name should contain "OpenAI"
    provider_class = agent._agent.llm.__class__.__name__  # type: ignore[attr-defined]
    assert "OpenAI" in provider_class


def test_detect_openai_from_o1_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """`o1-preview` → OpenAIProvider."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    agent = Agent(model="o1-preview")
    assert "OpenAI" in agent._agent.llm.__class__.__name__  # type: ignore[attr-defined]


def test_detect_anthropic_from_claude_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """`claude-sonnet-4` → AnthropicProvider."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    agent = Agent(model="claude-sonnet-4")
    assert "Anthropic" in agent._agent.llm.__class__.__name__  # type: ignore[attr-defined]


def test_explicit_openai_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """`openai:gpt-4o` explicit prefix overrides auto-detect."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    agent = Agent(model="openai:gpt-4o")
    assert "OpenAI" in agent._agent.llm.__class__.__name__  # type: ignore[attr-defined]


def test_explicit_anthropic_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """`anthropic:claude-haiku-4-5` explicit prefix."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    agent = Agent(model="anthropic:claude-haiku-4-5")
    assert "Anthropic" in agent._agent.llm.__class__.__name__  # type: ignore[attr-defined]


def test_unknown_model_raises() -> None:
    """Unknown model prefix without explicit provider → ValueError."""
    with pytest.raises(ValueError, match="Cannot auto-detect"):
        Agent(model="unknown-model-xyz-123")
