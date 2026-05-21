"""Phase 14.2 — Factory n_samples= wiring tests (Layer B)."""

from __future__ import annotations

import pytest

from ryuu import Agent
from ryuu._testing.fakes import FakeLLMProvider
from ryuu.providers.llm import Response, TokenUsage


def _fake(text: str) -> Response:
    return Response(
        content=text, model="fake",
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        finish_reason="stop",
    )


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")


async def test_factory_n_samples_majority_vote() -> None:
    """3 samples, majority wins."""
    agent = Agent(model="gpt-4o-mini", instructions="classify", n_samples=3, vote="majority")
    agent._agent.llm = FakeLLMProvider(responses=[  # type: ignore[attr-defined]
        _fake("A"), _fake("A"), _fake("B"),
    ])

    result = await agent.run("query")
    assert result.output == "A"
    assert "samples" in result.metadata
    assert result.metadata["best_of_n_confidence"] > 0.5


async def test_factory_n_samples_score_fn() -> None:
    """score_fn picks longest."""
    agent = Agent(
        model="gpt-4o-mini", instructions="...",
        n_samples=3, vote="score_fn", score_fn=lambda s: len(s),
    )
    agent._agent.llm = FakeLLMProvider(responses=[  # type: ignore[attr-defined]
        _fake("short"), _fake("medium_one"), _fake("longest_winner_here"),
    ])
    result = await agent.run("query")
    assert result.output == "longest_winner_here"


async def test_factory_n_samples_validation_negative() -> None:
    """n_samples < 1 → ValueError."""
    with pytest.raises(ValueError, match="n_samples"):
        Agent(model="gpt-4o-mini", instructions="...", n_samples=0)


def test_factory_n_samples_strategy_mutual_exclusion() -> None:
    """n_samples > 1 + strategy= → ValueError."""
    from ryuu_cognitive.strategies import BestOfNStrategy

    with pytest.raises(ValueError, match="strategy"):
        Agent(
            model="gpt-4o-mini", instructions="...",
            n_samples=3, strategy=BestOfNStrategy(n=3),
        )
