"""Tests for ReActCallbacks — SilentCallbacks + PrintCallbacks — L-05."""

from __future__ import annotations

import io
import sys
from dataclasses import dataclass
from typing import Any

import pytest

from uaaf._testing.fakes import FakeLLMProvider
from uaaf.execution.agent import AgentResult, Task
from uaaf.execution.llm_agent import LLMAgent, PrintCallbacks, ReActCallbacks, SilentCallbacks
from uaaf.observability.audit import AuditConfig, AuditLogger
from uaaf.observability.cost import CostPolicy, CostTracker
from uaaf.observability.rate_limit import RateLimiter, RatePolicy
from uaaf.observability.tracer import Tracer
from uaaf.providers.llm import CompletionRequest, Message, Response, TokenUsage
from uaaf.runtime.context import ExecutionContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resp(content: str, tool_calls: list[dict[str, Any]] | None = None) -> Response:
    meta: dict[str, Any] = {}
    if tool_calls:
        meta["tool_calls"] = tool_calls
    return Response(
        content=content,
        model="fake",
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        finish_reason="stop",
        metadata=meta,
    )


def _make_request() -> CompletionRequest:
    return CompletionRequest(
        messages=[Message(role="user", content="test")],
        model="fake",
    )


def _make_agent(llm: FakeLLMProvider, tool_registry: Any = None) -> StubAgent:
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    @dataclass
    class StubAgent(LLMAgent):
        async def _execute(self, task: Task, context: ExecutionContext) -> AgentResult:
            raise NotImplementedError

    return StubAgent(
        agent_id="stub",
        cost_tracker=CostTracker(policy=CostPolicy()),
        tracer=Tracer(service_name="test", exporter=InMemorySpanExporter()),
        audit_logger=AuditLogger(AuditConfig(backend="console")),
        rate_limiter=RateLimiter(policy=RatePolicy(rps=1000.0, burst=100)),
        llm=llm,
        tool_registry=tool_registry,
    )


# ---------------------------------------------------------------------------
# Protocol structural check
# ---------------------------------------------------------------------------

def test_silent_callbacks_satisfies_protocol() -> None:
    cb = SilentCallbacks()
    assert isinstance(cb, ReActCallbacks)


def test_print_callbacks_satisfies_protocol() -> None:
    cb = PrintCallbacks()
    assert isinstance(cb, ReActCallbacks)


# ---------------------------------------------------------------------------
# SilentCallbacks — no output (default for tests)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_react_loop_silent_callbacks_no_stdout() -> None:
    fake = FakeLLMProvider(responses=[_resp("done")])
    agent = _make_agent(fake)
    captured = io.StringIO()
    sys.stdout = captured
    try:
        await agent.react_loop(_make_request(), callbacks=SilentCallbacks())
    finally:
        sys.stdout = sys.__stdout__
    assert captured.getvalue() == ""


@pytest.mark.anyio
async def test_react_loop_default_callbacks_is_silent() -> None:
    """Default callbacks should not produce stdout (tests don't need capsys)."""
    fake = FakeLLMProvider(responses=[_resp("done")])
    agent = _make_agent(fake)
    captured = io.StringIO()
    sys.stdout = captured
    try:
        await agent.react_loop(_make_request())  # no callbacks arg
    finally:
        sys.stdout = sys.__stdout__
    assert captured.getvalue() == ""


# ---------------------------------------------------------------------------
# PrintCallbacks — produces output
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_react_loop_print_callbacks_final_answer_output(capsys: Any) -> None:
    fake = FakeLLMProvider(responses=[_resp("Final answer here.")])
    agent = _make_agent(fake)
    await agent.react_loop(_make_request(), callbacks=PrintCallbacks())
    out = capsys.readouterr().out
    assert "Final answer here." in out or "✅" in out


@pytest.mark.anyio
async def test_react_loop_print_callbacks_tool_round_output(capsys: Any) -> None:
    from uaaf.execution.tool_registry import ToolRegistry

    reg = ToolRegistry()

    async def ping(**kwargs: Any) -> str:
        return "pong"

    reg.register("ping", ping)

    fake = FakeLLMProvider(responses=[
        _resp("thinking...", tool_calls=[{"id": "c1", "function": {"name": "ping", "arguments": {}}}]),
        _resp("done after tool"),
    ])
    agent = _make_agent(fake, tool_registry=reg)
    await agent.react_loop(_make_request(), callbacks=PrintCallbacks())
    out = capsys.readouterr().out
    # Should have thought + action + observation markers
    assert "ping" in out
    assert "pong" in out


# ---------------------------------------------------------------------------
# Custom callbacks — hooks fire
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_react_loop_custom_callbacks_hooks_called() -> None:
    """Custom ReActCallbacks implementation receives hook calls."""
    from uaaf.execution.tool_registry import ToolRegistry

    events: list[str] = []

    class TrackingCallbacks(ReActCallbacks):
        async def on_thought(self, text: str) -> None:
            events.append(f"thought:{text}")

        async def on_action(self, tool_name: str, args: dict[str, Any]) -> None:
            events.append(f"action:{tool_name}")

        async def on_observation(self, tool_name: str, result: str) -> None:
            events.append(f"obs:{tool_name}")

        async def on_final(self, text: str) -> None:
            events.append(f"final:{text}")

    reg = ToolRegistry()

    async def noop(**kwargs: Any) -> str:
        return "ok"

    reg.register("noop", noop)

    fake = FakeLLMProvider(responses=[
        _resp("my thought", tool_calls=[{"id": "c1", "function": {"name": "noop", "arguments": {}}}]),
        _resp("my final"),
    ])
    agent = _make_agent(fake, tool_registry=reg)
    await agent.react_loop(_make_request(), callbacks=TrackingCallbacks())

    assert any("action:noop" == e for e in events)
    assert any(e.startswith("final:") for e in events)
