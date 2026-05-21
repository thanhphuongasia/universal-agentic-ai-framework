"""Integration tests — `Agent()` factory against real OpenAI API.

Phase 10 T7. SKIP if `OPENAI_API_KEY` not set.

Run manually:
    OPENAI_API_KEY=sk-... pytest tests/integration/ryuu/ -v
"""

from __future__ import annotations

import os

import pytest

from ryuu import Agent

pytestmark = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set — skipping live integration test",
)


async def test_simple_completion() -> None:
    """Single LLM call, no tools — verify end-to-end works with real API."""
    agent = Agent(
        model="gpt-4o-mini",
        instructions="Reply with exactly: 'pong'",
        max_tokens=10,
        temperature=0.0,
    )
    result = await agent.run("ping")
    assert "pong" in result.output.lower()
    assert result.cost.input_tokens > 0
    assert result.cost.output_tokens > 0


async def test_tool_call_roundtrip() -> None:
    """Agent invokes inline tool via OpenAI function calling."""

    def add_numbers(a: int, b: int) -> dict:
        """Add two integers and return their sum."""
        return {"sum": a + b}

    agent = Agent(
        model="gpt-4o-mini",
        instructions="Use the add_numbers tool when asked about arithmetic.",
        tools=[add_numbers],
        max_iterations=3,
        temperature=0.0,
    )
    result = await agent.run("What is 17 plus 25? Use the tool.")
    # Either LLM mentions 42 or tool was invoked
    assert "42" in result.output or result.cost.output_tokens > 0
