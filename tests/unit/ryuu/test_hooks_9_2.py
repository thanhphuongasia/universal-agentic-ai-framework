"""Phase 9.2 — Extended hooks (PRE/POST_TOOL, budget/rate events, parallel mode).

10 cases.
"""

from __future__ import annotations

import pytest

from ryuu import Agent
from ryuu._testing.fakes import FakeLLMProvider
from ryuu.hooks import (
    HookContext,
    HookEvent,
    HookRegistry,
    OnBudgetExceededContext,
    OnRateLimitedContext,
    PostToolContext,
    PreToolContext,
)
from ryuu.providers.llm import Response, TokenUsage
from ryuu_core.errors import BudgetExceededError, RateLimitTimeout
from ryuu_workflow.context import ContextScope


def _fake_response(text: str = "ok", tool_calls: list | None = None) -> Response:
    return Response(
        content=text,
        model="fake",
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        finish_reason="stop",
        metadata={"tool_calls": tool_calls} if tool_calls else {},
    )


def _tool_call(name: str, args: dict) -> dict:
    return {
        "id": "call_1",
        "function": {"name": name, "arguments": args},
    }


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")


# ── PRE_TOOL / POST_TOOL events ─────────────────────────────────────────────


async def test_pre_tool_fires_before_handler() -> None:
    """PRE_TOOL hook fires before tool handler executes."""
    fired = []

    async def hook(ctx: PreToolContext) -> None:
        fired.append((ctx.tool_name, dict(ctx.args)))

    async def my_tool(x: int) -> dict:
        """Demo."""
        return {"x_doubled": x * 2}

    agent = Agent(
        model="gpt-4o-mini",
        tools=[my_tool],
        hooks={"pre_tool": [hook]},
    )
    # LLM responds with tool_call then final answer
    agent._agent.llm = FakeLLMProvider(responses=[  # type: ignore[attr-defined]
        _fake_response("", tool_calls=[_tool_call("my_tool", {"x": 5})]),
        _fake_response("done"),
    ])

    await agent.run("hi")
    assert fired == [("my_tool", {"x": 5})]


async def test_post_tool_fires_with_result() -> None:
    """POST_TOOL hook receives handler's return value."""
    captured = {}

    async def hook(ctx: PostToolContext) -> None:
        captured["result"] = ctx.result
        captured["name"] = ctx.tool_name

    async def my_tool(x: int) -> dict:
        """Demo."""
        return {"computed": x * 100}

    agent = Agent(
        model="gpt-4o-mini",
        tools=[my_tool],
        hooks={"post_tool": [hook]},
    )
    agent._agent.llm = FakeLLMProvider(responses=[  # type: ignore[attr-defined]
        _fake_response("", tool_calls=[_tool_call("my_tool", {"x": 3})]),
        _fake_response("done"),
    ])

    await agent.run("hi")
    assert captured["name"] == "my_tool"
    assert captured["result"] == {"computed": 300}


async def test_pre_tool_can_mutate_args() -> None:
    """PRE_TOOL handler can replace args via ctx.replace(args=...)."""
    seen_x = []

    async def my_tool(x: int) -> dict:
        """Demo."""
        seen_x.append(x)
        return {"x": x}

    async def hook(ctx: PreToolContext) -> PreToolContext:
        # Mutate x to always be 999
        return ctx.replace(args={"x": 999})

    agent = Agent(
        model="gpt-4o-mini",
        tools=[my_tool],
        hooks={"pre_tool": [hook]},
    )
    agent._agent.llm = FakeLLMProvider(responses=[  # type: ignore[attr-defined]
        _fake_response("", tool_calls=[_tool_call("my_tool", {"x": 1})]),
        _fake_response("done"),
    ])

    await agent.run("hi")
    assert seen_x == [999]   # mutation applied


async def test_pre_tool_raise_blocks_call() -> None:
    """PRE_TOOL raise prevents handler from being called."""
    called = []

    async def my_tool(x: int) -> dict:
        """Demo."""
        called.append(x)
        return {}

    async def hook(ctx: PreToolContext) -> None:
        raise PermissionError("blocked by policy")

    agent = Agent(
        model="gpt-4o-mini",
        tools=[my_tool],
        hooks={"pre_tool": [hook]},
    )
    agent._agent.llm = FakeLLMProvider(responses=[  # type: ignore[attr-defined]
        _fake_response("", tool_calls=[_tool_call("my_tool", {"x": 1})]),
        _fake_response("done"),
    ])

    # ToolRegistry.run() catches exceptions and converts to JSON error response
    # to the LLM (so agent.run completes). What matters: handler NOT invoked.
    await agent.run("hi")
    assert called == []   # PRE_TOOL hook blocked → handler never invoked


# ── ON_BUDGET_EXCEEDED + ON_RATE_LIMITED ────────────────────────────────────


async def test_on_budget_exceeded_fires() -> None:
    """ON_BUDGET_EXCEEDED hook fires when BudgetExceededError raised."""
    fired = []

    async def hook(ctx: OnBudgetExceededContext) -> None:
        fired.append(type(ctx.error).__name__)

    agent = Agent(
        model="gpt-4o-mini",
        hooks={"on_budget_exceeded": [hook]},
    )
    agent._agent.llm = FakeLLMProvider(  # type: ignore[attr-defined]
        raise_on_call=BudgetExceededError("over budget"),
    )

    with pytest.raises(Exception):
        await agent.run("hi")
    assert fired == ["BudgetExceededError"]


async def test_on_rate_limited_fires() -> None:
    """ON_RATE_LIMITED hook fires when RateLimitTimeout raised."""
    fired = []

    async def hook(ctx: OnRateLimitedContext) -> None:
        fired.append(type(ctx.error).__name__)

    agent = Agent(
        model="gpt-4o-mini",
        hooks={"on_rate_limited": [hook]},
    )
    agent._agent.llm = FakeLLMProvider(  # type: ignore[attr-defined]
        raise_on_call=RateLimitTimeout("throttled"),
    )

    with pytest.raises(Exception):
        await agent.run("hi")
    assert fired == ["RateLimitTimeout"]


async def test_specialized_event_fires_and_generic_on_error_too() -> None:
    """When BudgetExceededError raised, BOTH on_budget_exceeded AND on_error fire."""
    fired = []

    async def budget_hook(ctx: OnBudgetExceededContext) -> None:
        fired.append("budget")

    async def err_hook(ctx) -> None:
        fired.append("error")

    agent = Agent(
        model="gpt-4o-mini",
        hooks={"on_budget_exceeded": [budget_hook], "on_error": [err_hook]},
    )
    agent._agent.llm = FakeLLMProvider(  # type: ignore[attr-defined]
        raise_on_call=BudgetExceededError("over"),
    )

    with pytest.raises(Exception):
        await agent.run("hi")
    assert fired == ["budget", "error"]


# ── Parallel mode ──────────────────────────────────────────────────────────


async def test_parallel_handler_runs_concurrently() -> None:
    """Parallel handlers fire concurrently — total time bounded by slowest, not sum."""
    import time
    timings = []

    async def slow_hook(ctx: HookContext) -> None:
        import anyio
        await anyio.sleep(0.05)
        timings.append(time.monotonic())

    registry = HookRegistry()
    for _ in range(3):
        registry.register(HookEvent.PRE_EXECUTE, slow_hook, mode="parallel")

    start = time.monotonic()
    ctx = HookContext(
        event=HookEvent.PRE_EXECUTE,
        correlation_id="c1",
        scope=ContextScope(user_id="u", session_id="s", domain="d"),
    )
    await registry.fire(HookEvent.PRE_EXECUTE, ctx)
    elapsed = time.monotonic() - start

    # If sequential, would take ~0.15s; parallel ~0.05s. Allow slack.
    assert elapsed < 0.12, f"parallel mode too slow: {elapsed:.3f}s"


async def test_parallel_handler_exception_swallowed() -> None:
    """Parallel handler raise is swallowed + logged, does NOT propagate."""
    called = []

    async def crashing(ctx: HookContext) -> None:
        raise RuntimeError("simulated crash")

    async def ok_hook(ctx: HookContext) -> None:
        called.append("ok")

    registry = HookRegistry()
    registry.register(HookEvent.ON_COMPLETE, crashing, mode="parallel")
    registry.register(HookEvent.ON_COMPLETE, ok_hook, mode="parallel")

    ctx = HookContext(
        event=HookEvent.ON_COMPLETE,
        correlation_id="c1",
        scope=ContextScope(user_id="u", session_id="s", domain="d"),
    )
    # Should NOT raise
    await registry.fire(HookEvent.ON_COMPLETE, ctx)
    assert called == ["ok"]


async def test_mixed_sequential_and_parallel_handlers() -> None:
    """Sequential fire first (in order), then parallel fire concurrently."""
    order: list[str] = []

    async def seq1(ctx: HookContext) -> None:
        order.append("seq1")

    async def seq2(ctx: HookContext) -> None:
        order.append("seq2")

    async def par1(ctx: HookContext) -> None:
        order.append("par")

    registry = HookRegistry()
    registry.register(HookEvent.PRE_EXECUTE, seq1, mode="sequential")
    registry.register(HookEvent.PRE_EXECUTE, par1, mode="parallel")
    registry.register(HookEvent.PRE_EXECUTE, seq2, mode="sequential")

    ctx = HookContext(
        event=HookEvent.PRE_EXECUTE,
        correlation_id="c1",
        scope=ContextScope(user_id="u", session_id="s", domain="d"),
    )
    await registry.fire(HookEvent.PRE_EXECUTE, ctx)

    # Sequential first in order, then parallel
    assert order[:2] == ["seq1", "seq2"]
    assert "par" in order
