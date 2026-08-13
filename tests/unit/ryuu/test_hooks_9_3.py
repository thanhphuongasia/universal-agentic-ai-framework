"""Phase 9.3 — wrap-style middleware tests (around_llm / around_tool)."""

from __future__ import annotations

import pytest

from ryuu_hooks.hooks import (
    HookEvent,
    HookRegistry,
    PreLLMContext,
    PreToolContext,
)
from ryuu_workflow.context import ContextScope


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _scope() -> ContextScope:
    return ContextScope(user_id="u1", session_id="s1", domain="test")


def _llm_ctx() -> PreLLMContext:
    return PreLLMContext(
        event=HookEvent.PRE_LLM,
        correlation_id="test-wrap",
        scope=_scope(),
        messages=[{"role": "user", "content": "hello"}],
        model="gpt-4o",
    )


def _tool_ctx() -> PreToolContext:
    return PreToolContext(
        event=HookEvent.PRE_TOOL,
        correlation_id="test-wrap",
        scope=_scope(),
        tool_name="search",
        args={"query": "cats"},
    )


# ---------------------------------------------------------------------------
# Basic passthrough
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_llm_wraps_no_handlers_calls_fn() -> None:
    registry = HookRegistry()
    called: list[str] = []

    async def base_fn(ctx: PreLLMContext) -> str:
        called.append("base")
        return "result"

    result = await registry.apply_llm_wraps(_llm_ctx(), base_fn)
    assert result == "result"
    assert called == ["base"]


@pytest.mark.asyncio
async def test_apply_tool_wraps_no_handlers_calls_fn() -> None:
    registry = HookRegistry()
    called: list[str] = []

    async def base_fn(ctx: PreToolContext) -> dict:
        called.append("base")
        return {"output": 42}

    result = await registry.apply_tool_wraps(_tool_ctx(), base_fn)
    assert result == {"output": 42}
    assert called == ["base"]


# ---------------------------------------------------------------------------
# Single wrap — can intercept before / after
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_around_llm_single_wrap() -> None:
    registry = HookRegistry()
    log: list[str] = []

    @registry.around_llm
    async def observe(next, ctx: PreLLMContext):  # type: ignore[type-arg]
        log.append("before")
        result = await next(ctx)
        log.append("after")
        return result

    async def base(ctx: PreLLMContext) -> str:
        log.append("base")
        return "ok"

    result = await registry.apply_llm_wraps(_llm_ctx(), base)
    assert result == "ok"
    assert log == ["before", "base", "after"]


@pytest.mark.asyncio
async def test_around_tool_single_wrap() -> None:
    registry = HookRegistry()
    log: list[str] = []

    @registry.around_tool
    async def observe(next, ctx: PreToolContext):  # type: ignore[type-arg]
        log.append("before")
        result = await next(ctx)
        log.append("after")
        return result

    async def base(ctx: PreToolContext) -> dict:
        log.append("base")
        return {}

    await registry.apply_tool_wraps(_tool_ctx(), base)
    assert log == ["before", "base", "after"]


# ---------------------------------------------------------------------------
# FIFO nesting order: first registered = outermost
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_around_llm_fifo_nesting_order() -> None:
    registry = HookRegistry()
    log: list[str] = []

    @registry.around_llm
    async def outer(next, ctx):  # type: ignore[type-arg]
        log.append("outer-before")
        r = await next(ctx)
        log.append("outer-after")
        return r

    @registry.around_llm
    async def inner(next, ctx):  # type: ignore[type-arg]
        log.append("inner-before")
        r = await next(ctx)
        log.append("inner-after")
        return r

    async def base(ctx: PreLLMContext) -> str:
        log.append("base")
        return "x"

    await registry.apply_llm_wraps(_llm_ctx(), base)
    assert log == ["outer-before", "inner-before", "base", "inner-after", "outer-after"]


# ---------------------------------------------------------------------------
# Retry pattern — call next multiple times
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_around_llm_retry_on_exception() -> None:
    registry = HookRegistry()
    attempts: list[int] = []

    @registry.around_llm
    async def retry(next, ctx):  # type: ignore[type-arg]
        for i in range(3):
            try:
                return await next(ctx)
            except ValueError:
                if i == 2:
                    raise
        return None  # unreachable

    call_count = 0

    async def flaky(ctx: PreLLMContext) -> str:
        nonlocal call_count
        call_count += 1
        attempts.append(call_count)
        if call_count < 3:
            raise ValueError("transient")
        return "success"

    result = await registry.apply_llm_wraps(_llm_ctx(), flaky)
    assert result == "success"
    assert call_count == 3


# ---------------------------------------------------------------------------
# Short-circuit / fallback — skip calling next
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_around_llm_short_circuit() -> None:
    registry = HookRegistry()
    base_called = False

    @registry.around_llm
    async def cached(next, ctx):  # type: ignore[type-arg]
        return "cached-result"  # never calls next

    async def base(ctx: PreLLMContext) -> str:
        nonlocal base_called
        base_called = True
        return "live-result"

    result = await registry.apply_llm_wraps(_llm_ctx(), base)
    assert result == "cached-result"
    assert base_called is False


# ---------------------------------------------------------------------------
# Context mutation — wrap can pass modified ctx to next
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_around_tool_mutate_ctx() -> None:
    registry = HookRegistry()
    received_args: list[dict] = []

    @registry.around_tool
    async def sanitize(next, ctx: PreToolContext):  # type: ignore[type-arg]
        mutated = ctx.replace(args={**ctx.args, "sanitized": True})
        return await next(mutated)

    async def base(ctx: PreToolContext) -> dict:
        received_args.append(dict(ctx.args))
        return {}

    await registry.apply_tool_wraps(_tool_ctx(), base)
    assert received_args[0]["sanitized"] is True
    assert received_args[0]["query"] == "cats"


# ---------------------------------------------------------------------------
# has_llm_wraps / has_tool_wraps predicates
# ---------------------------------------------------------------------------


def test_has_llm_wraps_false_when_empty() -> None:
    assert HookRegistry().has_llm_wraps() is False


def test_has_tool_wraps_false_when_empty() -> None:
    assert HookRegistry().has_tool_wraps() is False


def test_has_llm_wraps_true_after_register() -> None:
    registry = HookRegistry()

    @registry.around_llm
    async def h(next, ctx):  # type: ignore[type-arg]
        return await next(ctx)

    assert registry.has_llm_wraps() is True


def test_has_tool_wraps_true_after_register() -> None:
    registry = HookRegistry()

    @registry.around_tool
    async def h(next, ctx):  # type: ignore[type-arg]
        return await next(ctx)

    assert registry.has_tool_wraps() is True


# ---------------------------------------------------------------------------
# around_llm decorator returns the handler (useful for storing reference)
# ---------------------------------------------------------------------------


def test_around_llm_decorator_returns_handler() -> None:
    registry = HookRegistry()

    async def my_handler(next, ctx):  # type: ignore[type-arg]
        return await next(ctx)

    returned = registry.around_llm(my_handler)
    assert returned is my_handler


def test_around_tool_decorator_returns_handler() -> None:
    registry = HookRegistry()

    async def my_handler(next, ctx):  # type: ignore[type-arg]
        return await next(ctx)

    returned = registry.around_tool(my_handler)
    assert returned is my_handler


# ---------------------------------------------------------------------------
# Wrap handlers co-exist with fire() handlers — independent registries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wrap_and_fire_handlers_independent() -> None:
    """around_llm wraps and HookEvent.PRE_LLM fire handlers are separate."""
    registry = HookRegistry()
    fire_called = False
    wrap_called = False

    async def fire_handler(ctx):  # type: ignore[type-arg]
        nonlocal fire_called
        fire_called = True

    registry.register(HookEvent.PRE_LLM, fire_handler)

    @registry.around_llm
    async def wrap_handler(next, ctx):  # type: ignore[type-arg]
        nonlocal wrap_called
        wrap_called = True
        return await next(ctx)

    # fire() does NOT call wrap handlers
    await registry.fire(HookEvent.PRE_LLM, _llm_ctx())
    assert fire_called is True
    assert wrap_called is False

    # apply_llm_wraps() does NOT call fire handlers
    fire_called = False

    async def base(ctx: PreLLMContext) -> str:
        return "x"

    await registry.apply_llm_wraps(_llm_ctx(), base)
    assert wrap_called is True
    assert fire_called is False
