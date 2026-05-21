"""Phase 14.3 — Factory adaptive_compute= wiring tests (Layer B)."""

from __future__ import annotations

import pytest

from ryuu import Agent
from ryuu._testing.fakes import FakeLLMProvider
from ryuu.providers.llm import Response, TokenUsage


def _fake(text: str = "ok") -> Response:
    return Response(
        content=text, model="fake",
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        finish_reason="stop",
    )


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")


async def test_factory_adaptive_classifies_trivial() -> None:
    """Short greeting → trivial → gpt-4o-mini + max_iter=2."""
    agent = Agent(model="gpt-4o-mini", instructions="...", adaptive_compute=True)
    agent._agent.llm = FakeLLMProvider(responses=[_fake("hi")])  # type: ignore[attr-defined]

    result = await agent.run("hello")
    assert result.metadata["difficulty"] == "trivial"
    assert result.metadata["tier_model"] == "gpt-4o-mini"


async def test_factory_adaptive_classifies_hard() -> None:
    """Long analyze query → hard → gpt-4o."""
    agent = Agent(model="gpt-4o-mini", instructions="...", adaptive_compute=True)
    agent._agent.llm = FakeLLMProvider(responses=[_fake("complex result")])  # type: ignore[attr-defined]

    result = await agent.run("Analyze and compare these 3 architectures step by step")
    assert result.metadata["difficulty"] == "hard"
    assert result.metadata["tier_model"] == "gpt-4o"


async def test_factory_adaptive_custom_tier_models() -> None:
    """User overrides tier_models — hard tier uses custom model."""
    agent = Agent(
        model="gpt-4o-mini", instructions="...",
        adaptive_compute=True,
        tier_models={"trivial": "gpt-3.5", "medium": "gpt-4o-mini", "hard": "claude-opus"},
    )
    agent._agent.llm = FakeLLMProvider(responses=[_fake("result")])  # type: ignore[attr-defined]

    result = await agent.run("Analyze architecture in depth")
    assert result.metadata["tier_model"] == "claude-opus"


def test_factory_adaptive_strategy_mutual_exclusion() -> None:
    """adaptive_compute=True + strategy= → ValueError."""
    from ryuu_cognitive.strategies import AdaptiveStrategy

    with pytest.raises(ValueError, match="strategy"):
        Agent(
            model="gpt-4o-mini", instructions="...",
            adaptive_compute=True,
            strategy=AdaptiveStrategy(),
        )
