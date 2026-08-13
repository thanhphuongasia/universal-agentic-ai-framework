"""Phase 9.3 — Factory integration tests for wrap-style middleware.

Verifies that around_llm / around_tool handlers registered via Agent(...)
fields actually fire through the execution path.
"""

from __future__ import annotations

import pytest

from ryuu import Agent
from ryuu._testing.fakes import FakeLLMProvider
from ryuu.hooks import PreLLMContext, PreToolContext
from ryuu.providers.llm import Response, TokenUsage


def _resp(text: str = "ok", tool_calls: list | None = None) -> Response:
    return Response(
        content=text,
        model="fake",
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        finish_reason="stop",
        metadata={"tool_calls": tool_calls} if tool_calls else {},
    )


def _tool_call(name: str, args: dict) -> dict:
    return {"id": "call_1", "function": {"name": name, "arguments": args}}


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")


# ---------------------------------------------------------------------------
# around_llm — basic wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_around_llm_fires_via_factory_field() -> None:
    """around_llm handler registered via Agent field is called on run()."""
    log: list[str] = []

    async def observe(next, ctx: PreLLMContext):  # type: ignore[type-arg]
        log.append("before")
        result = await next(ctx)
        log.append("after")
        return result

    agent = Agent(model="gpt-4o-mini", around_llm=[observe])
    agent._agent.llm = FakeLLMProvider(responses=[_resp("hello")])  # type: ignore[attr-defined]

    result = await agent.run("hi")
    assert result.output == "hello"
    assert log == ["before", "after"]


@pytest.mark.asyncio
async def test_around_llm_retry_through_factory() -> None:
    """Retry pattern: around_llm retries on exception; succeeds on 3rd attempt."""
    attempts: list[int] = []
    attempt = 0

    async def retry(next, ctx: PreLLMContext):  # type: ignore[type-arg]
        nonlocal attempt
        for i in range(3):
            try:
                return await next(ctx)
            except ValueError:
                if i == 2:
                    raise
        return None  # unreachable

    agent = Agent(model="gpt-4o-mini", around_llm=[retry])
    fake = FakeLLMProvider(
        responses=[_resp("success")],
        raise_on_call=None,
    )

    call_n = 0

    original_complete = fake.complete

    async def flaky_complete(request):  # type: ignore[type-arg]
        nonlocal call_n
        call_n += 1
        attempts.append(call_n)
        if call_n < 3:
            raise ValueError("transient")
        return await original_complete(request)

    fake.complete = flaky_complete  # type: ignore[method-assign]
    agent._agent.llm = fake  # type: ignore[attr-defined]

    result = await agent.run("test")
    assert result.output == "success"
    assert call_n == 3


@pytest.mark.asyncio
async def test_around_llm_short_circuit_skips_provider() -> None:
    """Short-circuit: around_llm returns without calling next; provider never called."""
    provider_called = False

    async def cached(next, ctx: PreLLMContext):  # type: ignore[type-arg]
        # Return a fake (output, usage) tuple without calling the LLM
        from ryuu.providers.llm import TokenUsage
        return "cached answer", TokenUsage(input_tokens=0, output_tokens=0)

    fake = FakeLLMProvider()

    original_complete = fake.complete

    async def track_complete(request):  # type: ignore[type-arg]
        nonlocal provider_called
        provider_called = True
        return await original_complete(request)

    fake.complete = track_complete  # type: ignore[method-assign]

    agent = Agent(model="gpt-4o-mini", around_llm=[cached])
    agent._agent.llm = fake  # type: ignore[attr-defined]

    result = await agent.run("test")
    assert result.output == "cached answer"
    assert provider_called is False


@pytest.mark.asyncio
async def test_around_llm_fifo_nesting_order_via_factory() -> None:
    """Multiple around_llm handlers nest FIFO (first registered = outermost)."""
    log: list[str] = []

    async def outer(next, ctx):  # type: ignore[type-arg]
        log.append("outer-before")
        r = await next(ctx)
        log.append("outer-after")
        return r

    async def inner(next, ctx):  # type: ignore[type-arg]
        log.append("inner-before")
        r = await next(ctx)
        log.append("inner-after")
        return r

    agent = Agent(model="gpt-4o-mini", around_llm=[outer, inner])
    agent._agent.llm = FakeLLMProvider(responses=[_resp()])  # type: ignore[attr-defined]

    await agent.run("test")
    assert log == ["outer-before", "inner-before", "inner-after", "outer-after"]


# ---------------------------------------------------------------------------
# around_tool — basic wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_around_tool_fires_via_factory_field() -> None:
    """around_tool handler registered via Agent field wraps tool calls."""
    log: list[str] = []

    async def observe(next, ctx: PreToolContext):  # type: ignore[type-arg]
        log.append(f"before:{ctx.tool_name}")
        result = await next(ctx)
        log.append(f"after:{ctx.tool_name}")
        return result

    async def my_tool(x: int) -> dict:
        return {"value": x * 2}

    agent = Agent(model="gpt-4o-mini", tools=[my_tool], around_tool=[observe])
    agent._agent.llm = FakeLLMProvider(  # type: ignore[attr-defined]
        responses=[
            _resp("", tool_calls=[_tool_call("my_tool", {"x": 3})]),
            _resp("done"),
        ]
    )

    result = await agent.run("test")
    assert result.output == "done"
    assert log == ["before:my_tool", "after:my_tool"]


@pytest.mark.asyncio
async def test_around_tool_can_mutate_args_via_factory() -> None:
    """around_tool can modify ctx.args before passing to the real handler."""
    received: list[dict] = []

    async def sanitize(next, ctx: PreToolContext):  # type: ignore[type-arg]
        mutated = ctx.replace(args={**ctx.args, "sanitized": True})
        return await next(mutated)

    async def my_tool(x: int, sanitized: bool = False) -> dict:
        received.append({"x": x, "sanitized": sanitized})
        return {"ok": True}

    agent = Agent(model="gpt-4o-mini", tools=[my_tool], around_tool=[sanitize])
    agent._agent.llm = FakeLLMProvider(  # type: ignore[attr-defined]
        responses=[
            _resp("", tool_calls=[_tool_call("my_tool", {"x": 7})]),
            _resp("done"),
        ]
    )

    await agent.run("test")
    assert received[0]["sanitized"] is True
    assert received[0]["x"] == 7


# ---------------------------------------------------------------------------
# Coexistence: around_* + fire-style hooks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_around_llm_coexists_with_fire_hooks() -> None:
    """around_llm and hooks=pre_llm both fire independently on same run()."""
    wrap_called = False
    fire_called = False

    async def wrap_handler(next, ctx):  # type: ignore[type-arg]
        nonlocal wrap_called
        wrap_called = True
        return await next(ctx)

    async def fire_handler(ctx: PreLLMContext) -> None:
        nonlocal fire_called
        fire_called = True

    agent = Agent(
        model="gpt-4o-mini",
        around_llm=[wrap_handler],
        hooks={"pre_llm": [fire_handler]},
    )
    agent._agent.llm = FakeLLMProvider(responses=[_resp()])  # type: ignore[attr-defined]

    await agent.run("test")
    assert wrap_called is True
    assert fire_called is True


@pytest.mark.asyncio
async def test_around_tool_coexists_with_pre_tool_hook() -> None:
    """around_tool and hooks=pre_tool both fire on the same tool call."""
    wrap_called = False
    fire_called = False

    async def wrap_handler(next, ctx: PreToolContext):  # type: ignore[type-arg]
        nonlocal wrap_called
        wrap_called = True
        return await next(ctx)

    async def fire_handler(ctx: PreToolContext) -> None:
        nonlocal fire_called
        fire_called = True

    async def my_tool(x: int) -> dict:
        return {}

    agent = Agent(
        model="gpt-4o-mini",
        tools=[my_tool],
        around_tool=[wrap_handler],
        hooks={"pre_tool": [fire_handler]},
    )
    agent._agent.llm = FakeLLMProvider(  # type: ignore[attr-defined]
        responses=[
            _resp("", tool_calls=[_tool_call("my_tool", {"x": 1})]),
            _resp("done"),
        ]
    )

    await agent.run("test")
    assert wrap_called is True
    assert fire_called is True


# ---------------------------------------------------------------------------
# Zero-overhead: no wraps registered → direct path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_around_llm_fires_on_stream() -> None:
    """around_llm wrap is also called when agent.stream() is used (no-tool path)."""
    log: list[str] = []

    async def observe(next, ctx: PreLLMContext):  # type: ignore[type-arg]
        log.append("wrap-before")
        result = await next(ctx)
        log.append("wrap-after")
        return result

    agent = Agent(model="gpt-4o-mini", around_llm=[observe])
    agent._agent.llm = FakeLLMProvider(responses=[_resp("streamed")])  # type: ignore[attr-defined]

    events = [ev async for ev in agent.stream("hi")]
    final = next(e for e in events if e.type == "final")
    assert final.text == "streamed"
    assert log == ["wrap-before", "wrap-after"]


@pytest.mark.asyncio
async def test_no_around_llm_takes_direct_path() -> None:
    """When around_llm is not set, execution takes the direct path (no wrap overhead)."""
    agent = Agent(model="gpt-4o-mini")
    agent._agent.llm = FakeLLMProvider(responses=[_resp("direct")])  # type: ignore[attr-defined]

    result = await agent.run("test")
    assert result.output == "direct"
    assert agent._agent._hook_registry is None  # type: ignore[attr-defined]
