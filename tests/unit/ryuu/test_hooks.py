"""Phase 9 — Hook system tests.

10 cases covering registry behavior + Factory integration.
"""

from __future__ import annotations

import pytest

from ryuu import Agent
from ryuu._testing.fakes import FakeLLMProvider
from ryuu.hooks import (
    HookContext,
    HookEvent,
    HookRegistry,
    OnCompleteContext,
    OnErrorContext,
    PostExecuteContext,
    PostLLMContext,
    PreExecuteContext,
    PreLLMContext,
)
from ryuu.providers.llm import Response, TokenUsage
from ryuu_workflow.context import ContextScope


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


# ── HookRegistry — basic ───────────────────────────────────────────────────


async def test_registry_fires_handler_for_event() -> None:
    """Single handler registered + fired on event."""
    registry = HookRegistry()
    called = []

    async def handler(ctx: HookContext) -> None:
        called.append(ctx.event)

    registry.register(HookEvent.PRE_EXECUTE, handler)
    ctx = PreExecuteContext(
        event=HookEvent.PRE_EXECUTE,
        correlation_id="c1",
        scope=ContextScope(user_id="u", session_id="s", domain="d"),
    )
    await registry.fire(HookEvent.PRE_EXECUTE, ctx)
    assert called == [HookEvent.PRE_EXECUTE]


async def test_registry_multiple_handlers_sequential() -> None:
    """Multiple handlers fire in registration order."""
    registry = HookRegistry()
    order = []

    async def h1(ctx: HookContext) -> None:
        order.append(1)

    async def h2(ctx: HookContext) -> None:
        order.append(2)

    async def h3(ctx: HookContext) -> None:
        order.append(3)

    for h in (h1, h2, h3):
        registry.register(HookEvent.PRE_LLM, h)

    ctx = PreLLMContext(
        event=HookEvent.PRE_LLM,
        correlation_id="c1",
        scope=ContextScope(user_id="u", session_id="s", domain="d"),
    )
    await registry.fire(HookEvent.PRE_LLM, ctx)
    assert order == [1, 2, 3]


async def test_registry_handler_can_raise_to_block() -> None:
    """Handler raising stops chain + propagates."""
    registry = HookRegistry()

    async def blocking_handler(ctx: HookContext) -> None:
        raise PermissionError("blocked by policy")

    registry.register(HookEvent.PRE_EXECUTE, blocking_handler)
    ctx = PreExecuteContext(
        event=HookEvent.PRE_EXECUTE,
        correlation_id="c1",
        scope=ContextScope(user_id="u", session_id="s", domain="d"),
    )
    with pytest.raises(PermissionError, match="blocked"):
        await registry.fire(HookEvent.PRE_EXECUTE, ctx)


def test_registry_register_dict_convenience() -> None:
    """register_dict({event: [handlers]}) wires many at once."""
    registry = HookRegistry()

    def h(ctx: HookContext) -> None:
        pass

    registry.register_dict({
        "pre_execute": [h, h],
        HookEvent.POST_EXECUTE: [h],
    })
    assert registry.has_handlers(HookEvent.PRE_EXECUTE)
    assert registry.has_handlers(HookEvent.POST_EXECUTE)


async def test_registry_sync_handler_supported() -> None:
    """Plain (non-async) handler also supported."""
    registry = HookRegistry()
    called = []

    def sync_handler(ctx: HookContext) -> None:
        called.append("sync")

    registry.register(HookEvent.ON_COMPLETE, sync_handler)
    ctx = OnCompleteContext(
        event=HookEvent.ON_COMPLETE,
        correlation_id="c1",
        scope=ContextScope(user_id="u", session_id="s", domain="d"),
    )
    await registry.fire(HookEvent.ON_COMPLETE, ctx)
    assert called == ["sync"]


# ── Factory hooks= integration ─────────────────────────────────────────────


async def test_factory_hooks_pre_execute_fires() -> None:
    """Agent(hooks={...}) fires PRE_EXECUTE before .run() executes."""
    fired = []

    async def hook(ctx: PreExecuteContext) -> None:
        fired.append("pre_execute")

    agent = Agent(
        model="gpt-4o-mini",
        hooks={"pre_execute": [hook]},
    )
    agent._agent.llm = FakeLLMProvider(responses=[_fake_response()])  # type: ignore[attr-defined]

    await agent.run("hi")
    assert fired == ["pre_execute"]


async def test_factory_hooks_post_execute_receives_result() -> None:
    """POST_EXECUTE handler receives AgentResult in ctx."""
    captured = {}

    async def hook(ctx: PostExecuteContext) -> None:
        captured["output"] = ctx.result.output if ctx.result else None

    agent = Agent(
        model="gpt-4o-mini",
        hooks={"post_execute": [hook]},
    )
    agent._agent.llm = FakeLLMProvider(responses=[_fake_response("hello world")])  # type: ignore[attr-defined]

    await agent.run("hi")
    assert captured["output"] == "hello world"


async def test_factory_hooks_pre_llm_fires_before_completion() -> None:
    """PRE_LLM hook fires before provider.complete()."""
    fired = []

    async def hook(ctx: PreLLMContext) -> None:
        fired.append(("pre_llm", len(ctx.messages)))

    agent = Agent(
        model="gpt-4o-mini",
        hooks={"pre_llm": [hook]},
    )
    agent._agent.llm = FakeLLMProvider(responses=[_fake_response()])  # type: ignore[attr-defined]

    await agent.run("hi")
    assert fired[0][0] == "pre_llm"
    assert fired[0][1] >= 1  # at least 1 message


async def test_factory_hooks_on_error_fires_on_exception() -> None:
    """ON_ERROR hook fires when execute raises."""
    fired = []

    async def hook(ctx: OnErrorContext) -> None:
        fired.append(type(ctx.error).__name__)

    agent = Agent(
        model="gpt-4o-mini",
        hooks={"on_error": [hook]},
    )
    # FakeLLMProvider that always raises
    agent._agent.llm = FakeLLMProvider(raise_on_call=RuntimeError("simulated"))  # type: ignore[attr-defined]

    # BaseAgent wraps unexpected exceptions in FatalError, so accept any Exception
    with pytest.raises(Exception):
        await agent.run("hi")
    # Hook still fires with original RuntimeError before BaseAgent wraps it
    assert fired == ["RuntimeError"]


async def test_factory_hooks_on_complete_fires_on_success() -> None:
    """ON_COMPLETE fires after successful execution."""
    fired = []

    async def hook(ctx: OnCompleteContext) -> None:
        fired.append("complete")

    agent = Agent(
        model="gpt-4o-mini",
        hooks={"on_complete": [hook]},
    )
    agent._agent.llm = FakeLLMProvider(responses=[_fake_response()])  # type: ignore[attr-defined]

    await agent.run("hi")
    assert fired == ["complete"]
