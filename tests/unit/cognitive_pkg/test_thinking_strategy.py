"""Phase 14.1 — ThinkingStrategy tests (Layer A — mechanism).

6 cases. Strategy wraps any base strategy with <thinking>/<answer> tags,
parses output → CognitiveResult with reasoning extracted.

Tests cognitive layer ISOLATED from Factory (no Agent class).
"""

from __future__ import annotations

import pytest

from ryuu_cognitive.strategies.thinking_strategy import ThinkingStrategy
from ryuu_cognitive.strategy import IAgentPool, IVerifier
from ryuu_core.context import ContextScope, ExecutionContext
from ryuu_core.models import (
    AgentResult,
    CognitiveResult,
    ComplexityLevel,
    Cost,
    StructuredIntent,
    Task,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_intent(action: str = "test query") -> StructuredIntent:
    return StructuredIntent(
        intent_type="query",
        action=action,
        entities={},
        complexity=ComplexityLevel.LOW,
        confidence=0.9,
    )


def _make_ctx() -> ExecutionContext:
    return ExecutionContext(
        scope=ContextScope(user_id="u1", session_id="s1", domain="test"),
        correlation_id="c1",
    )


class _FakeAgentPool:
    """Returns canned output for dispatch."""

    def __init__(self, canned_output: str) -> None:
        self.canned_output = canned_output
        self.dispatched: list[Task] = []

    async def dispatch(self, task: Task) -> AgentResult:
        self.dispatched.append(task)
        return AgentResult(
            task_id=task.task_id,
            output=self.canned_output,
            cost=Cost(input_tokens=10, output_tokens=5, usd=0.0001, provider="fake", model="fake"),
        )


class _NoopVerifier:
    async def verify(self, *args, **kwargs):
        return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_thinking_strategy_parses_both_tags() -> None:
    """ThinkingStrategy extracts <answer> as content + <thinking> as reasoning."""
    strategy = ThinkingStrategy()
    pool = _FakeAgentPool(
        "<thinking>Step 1: identify pattern. Step 2: apply rule.</thinking>\n"
        "<answer>The answer is 42.</answer>"
    )
    result = await strategy.execute(_make_intent(), _make_ctx(), pool, _NoopVerifier())

    assert isinstance(result, CognitiveResult)
    assert "The answer is 42." in result.content
    assert "<thinking>" not in result.content    # stripped
    assert "Step 1" in result.reasoning
    assert "apply rule" in result.reasoning


async def test_thinking_strategy_strategy_id() -> None:
    """strategy_id = 'thinking' for routing."""
    strategy = ThinkingStrategy()
    assert strategy.strategy_id == "thinking"


async def test_thinking_strategy_applicable_universal() -> None:
    """ThinkingStrategy applies to any intent (universal wrapper)."""
    strategy = ThinkingStrategy()
    assert strategy.applicable(_make_intent(), _make_ctx()) is True


async def test_thinking_strategy_malformed_output_fallback() -> None:
    """Output without tags → content = raw, thinking = empty (graceful fallback)."""
    strategy = ThinkingStrategy()
    pool = _FakeAgentPool("Just plain text, no tags here.")
    result = await strategy.execute(_make_intent(), _make_ctx(), pool, _NoopVerifier())

    assert "plain text" in result.content
    assert result.reasoning == ""


async def test_thinking_strategy_injects_template_into_task() -> None:
    """Strategy injects thinking template into dispatched Task's payload."""
    strategy = ThinkingStrategy()
    pool = _FakeAgentPool("<answer>x</answer>")
    await strategy.execute(_make_intent("analyze X"), _make_ctx(), pool, _NoopVerifier())

    # Task payload should carry a thinking_template hint or be visible somehow
    assert len(pool.dispatched) == 1
    task = pool.dispatched[0]
    # The implementation augments payload with thinking instruction
    assert (
        "<thinking>" in str(task.payload.get("system_prompt_suffix", ""))
        or task.payload.get("thinking_mode") is True
    )


async def test_thinking_strategy_estimate_cost() -> None:
    """estimate_cost returns positive estimate (+~20% over base for thinking overhead)."""
    strategy = ThinkingStrategy()
    estimate = strategy.estimate_cost(_make_intent(), _make_ctx())
    assert estimate.input_tokens_est > 0
    assert estimate.output_tokens_est > 0
    # Thinking adds ~200 output tokens for reasoning block
    assert estimate.output_tokens_est >= 300
