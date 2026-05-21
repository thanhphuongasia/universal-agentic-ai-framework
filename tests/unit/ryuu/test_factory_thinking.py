"""Phase 14.1 — Factory thinking_mode wiring tests (Layer B).

3 cases. Verify Factory `Agent(thinking_mode=True)` augments system prompt
+ parses output into `AgentResult.thinking` field.

Separate from Layer A (test_thinking_strategy.py) — these test Factory
integration end-to-end via FakeLLMProvider.
"""

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


async def test_factory_thinking_mode_parses_tags() -> None:
    """`Agent(thinking_mode=True)` → AgentResult.thinking populated, .output cleaned."""
    agent = Agent(
        model="gpt-4o-mini",
        instructions="Solve math problems",
        thinking_mode=True,
    )
    agent._agent.llm = FakeLLMProvider(responses=[_fake(  # type: ignore[attr-defined]
        "<thinking>17 × 23 = (17 × 20) + (17 × 3) = 340 + 51 = 391</thinking>\n"
        "<answer>391</answer>"
    )])

    result = await agent.run("What is 17 × 23?")
    assert result.output == "391"
    assert "17 × 23" in result.thinking
    assert "<thinking>" not in result.output


async def test_factory_thinking_mode_false_default() -> None:
    """Default `thinking_mode=False` → AgentResult.thinking is empty string."""
    agent = Agent(model="gpt-4o-mini", instructions="be brief")
    agent._agent.llm = FakeLLMProvider(responses=[_fake("plain output")])  # type: ignore[attr-defined]

    result = await agent.run("hi")
    assert result.output == "plain output"
    assert result.thinking == ""


async def test_factory_thinking_mode_malformed_fallback() -> None:
    """Output missing tags → output = raw, thinking = '' (graceful)."""
    agent = Agent(
        model="gpt-4o-mini",
        instructions="...",
        thinking_mode=True,
    )
    agent._agent.llm = FakeLLMProvider(responses=[  # type: ignore[attr-defined]
        _fake("No tags here, just plain reply."),
    ])

    result = await agent.run("query")
    assert "plain reply" in result.output
    assert result.thinking == ""


def test_factory_strategy_thinking_mode_mutual_exclusion() -> None:
    """Setting both `strategy=` and `thinking_mode=True` → ValueError."""
    from ryuu_cognitive.strategies import ThinkingStrategy

    with pytest.raises(ValueError, match="strategy.*thinking_mode|thinking_mode.*strategy"):
        Agent(
            model="gpt-4o-mini",
            instructions="...",
            thinking_mode=True,
            strategy=ThinkingStrategy(),
        )
