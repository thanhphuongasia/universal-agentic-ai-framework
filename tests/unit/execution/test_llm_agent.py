"""Tests for ryuu.execution.llm_agent — LLMAgent + react_loop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from ryuu._testing.fakes import FakeLLMProvider
from ryuu.execution.agent import AgentResult, Task
from ryuu.execution.llm_agent import LLMAgent
from ryuu.execution.tool_registry import ToolRegistry
from ryuu.observability.audit import AuditConfig, AuditLogger
from ryuu.observability.cost import Cost, CostPolicy, CostTracker
from ryuu.observability.rate_limit import RateLimiter, RatePolicy
from ryuu.observability.tracer import Tracer
from ryuu.providers.llm import CompletionRequest, Message, Response, TokenUsage
from ryuu_workflow.context import ContextScope, ExecutionContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tracer() -> Tracer:
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    return Tracer(service_name="test", exporter=InMemorySpanExporter())


def _make_context() -> ExecutionContext:
    scope = ContextScope(user_id="u1", session_id="s1", domain="test")
    return ExecutionContext(scope=scope, correlation_id="corr-1")


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


def _tool_call(name: str, args: dict[str, Any], call_id: str = "c1") -> dict[str, Any]:
    return {"id": call_id, "function": {"name": name, "arguments": args}}


def _make_request(query: str = "test query") -> CompletionRequest:
    return CompletionRequest(
        messages=[Message(role="user", content=query)],
        model="fake",
    )


def _make_agent(
    llm: FakeLLMProvider,
    tool_registry: ToolRegistry | None = None,
    audit_token_usage: bool = False,
) -> MinimalLLMAgent:
    return MinimalLLMAgent(
        agent_id="test-llm-agent",
        cost_tracker=CostTracker(policy=CostPolicy()),
        tracer=_make_tracer(),
        audit_logger=AuditLogger(AuditConfig(backend="console")),
        rate_limiter=RateLimiter(policy=RatePolicy(rps=1000.0, burst=100)),
        llm=llm,
        tool_registry=tool_registry,
        audit_token_usage=audit_token_usage,
    )


@dataclass
class MinimalLLMAgent(LLMAgent):
    """Concrete LLMAgent for testing — _execute just calls react_loop."""

    async def _execute(self, task: Task, context: ExecutionContext) -> AgentResult:
        request = _make_request(str(task.payload.get("query", "")))
        text, usage = await self._react_loop(request)
        return AgentResult(
            task_id=task.task_id,
            output=text,
            cost=Cost.zero(provider="fake", model="fake"),
        )


# ---------------------------------------------------------------------------
# Case 1: No tool_calls at round 1 → immediate final answer
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_react_loop_no_tools_returns_immediately() -> None:
    fake = FakeLLMProvider(responses=[_resp("Final answer.")])
    agent = _make_agent(fake)
    text, usage = await agent._react_loop(_make_request())
    assert text == "Final answer."
    assert fake.call_count == 1


@pytest.mark.anyio
async def test_react_loop_accumulates_token_usage() -> None:
    fake = FakeLLMProvider(responses=[_resp("Done.")])
    agent = _make_agent(fake)
    _, usage = await agent._react_loop(_make_request())
    assert usage.input_tokens == 10
    assert usage.output_tokens == 5


# ---------------------------------------------------------------------------
# Case 2: Tool_calls → multi-round Thought→Action→Observation
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_react_loop_executes_tool_and_continues() -> None:
    reg = ToolRegistry()
    async def ping(**kwargs: Any) -> str:
        return "pong"
    reg.register("ping", ping)

    fake = FakeLLMProvider(responses=[
        _resp("thinking...", tool_calls=[_tool_call("ping", {})]),
        _resp("Final after tool."),
    ])
    agent = _make_agent(fake, tool_registry=reg)
    text, usage = await agent._react_loop(_make_request())
    assert text == "Final after tool."
    assert fake.call_count == 2


@pytest.mark.anyio
async def test_react_loop_appends_tool_messages_correctly() -> None:
    """Assistant + tool messages must appear in subsequent request."""
    reg = ToolRegistry()
    async def noop(**kwargs: Any) -> str:
        return "result"
    reg.register("noop", noop)

    fake = FakeLLMProvider(responses=[
        _resp("step1", tool_calls=[_tool_call("noop", {}, call_id="id_abc")]),
        _resp("done"),
    ])
    agent = _make_agent(fake, tool_registry=reg)
    await agent._react_loop(_make_request())

    second_request = fake.last_request
    assert second_request is not None
    roles = [m.role for m in second_request.messages]
    assert "assistant" in roles
    assert "tool" in roles
    tool_msg = next(m for m in second_request.messages if m.role == "tool")
    assert tool_msg.tool_call_id == "id_abc"


@pytest.mark.anyio
async def test_react_loop_accumulates_tokens_across_rounds() -> None:
    reg = ToolRegistry()
    async def noop(**kwargs: Any) -> str:
        return "ok"
    reg.register("noop", noop)

    fake = FakeLLMProvider(responses=[
        _resp("t", tool_calls=[_tool_call("noop", {})]),
        _resp("final"),
    ])
    agent = _make_agent(fake, tool_registry=reg)
    _, usage = await agent._react_loop(_make_request())
    assert usage.input_tokens == 20   # 10 + 10
    assert usage.output_tokens == 10  # 5 + 5


# ---------------------------------------------------------------------------
# Case 3: Round N>1 returns tool_calls=[] → treat as final answer
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_react_loop_empty_tool_calls_mid_round_terminates_cleanly() -> None:
    reg = ToolRegistry()
    async def noop(**kwargs: Any) -> str:
        return "ok"
    reg.register("noop", noop)

    fake = FakeLLMProvider(responses=[
        _resp("round1", tool_calls=[_tool_call("noop", {})]),
        _resp("changed mind", tool_calls=[]),  # LLM changed mind — no tools
        _resp("should not be called"),
    ])
    agent = _make_agent(fake, tool_registry=reg)
    text, _ = await agent._react_loop(_make_request())
    assert text == "changed mind"
    assert fake.call_count == 2  # did not proceed to round 3


# ---------------------------------------------------------------------------
# Case 4: Max rounds exceeded → synthesis request without tools
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_react_loop_max_rounds_triggers_synthesis() -> None:
    reg = ToolRegistry()
    async def noop(**kwargs: Any) -> str:
        return "ok"
    reg.register("noop", noop)

    # All 2 rounds have tool_calls → exceeds max_rounds=2 → synthesis
    fake = FakeLLMProvider(responses=[
        _resp("r1", tool_calls=[_tool_call("noop", {})]),
        _resp("r2", tool_calls=[_tool_call("noop", {})]),
        _resp("synthesized"),
    ])
    agent = _make_agent(fake, tool_registry=reg)
    text, _ = await agent._react_loop(_make_request(), max_rounds=2)
    assert text == "synthesized"
    assert fake.call_count == 3


@pytest.mark.anyio
async def test_react_loop_synthesis_request_has_no_tools() -> None:
    reg = ToolRegistry()
    async def noop(**kwargs: Any) -> str:
        return "ok"
    reg.register("noop", noop)

    fake = FakeLLMProvider(responses=[
        _resp("r1", tool_calls=[_tool_call("noop", {})]),
        _resp("synthesis result"),
    ])
    agent = _make_agent(fake, tool_registry=reg)
    await agent._react_loop(_make_request(), max_rounds=1)

    # Synthesis request must not include tools (to avoid infinite loop)
    synth_req = fake.last_request
    assert synth_req is not None
    assert synth_req.tools is None


# ---------------------------------------------------------------------------
# LLMAgent is still abstract — cannot instantiate directly
# ---------------------------------------------------------------------------

def test_llm_agent_is_abstract() -> None:
    import inspect
    assert inspect.isabstract(LLMAgent)


# ---------------------------------------------------------------------------
# domain param flows into tool registry
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_react_loop_domain_enforced_by_registry() -> None:
    reg = ToolRegistry()
    async def ping(**kwargs: Any) -> str:
        return "pong"
    reg.register("ping", ping, allowed_domains={"todo"})

    fake = FakeLLMProvider(responses=[
        _resp("thinking", tool_calls=[_tool_call("ping", {})]),
        _resp("done"),
    ])
    agent = _make_agent(fake, tool_registry=reg)

    # Wrong domain raises PermissionError
    with pytest.raises(PermissionError):
        await agent._react_loop(_make_request(), domain="stock")


# ---------------------------------------------------------------------------
# Step trace (Bedrock-style): model/tool/synthesis steps with io + usage
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_react_loop_records_step_trace() -> None:
    from ryuu_execution.step_trace import StepTraceRecorder

    async def echo(**kwargs: Any) -> str:
        return "tool says hi"

    registry = ToolRegistry()
    registry.register("echo", echo)
    llm = FakeLLMProvider(responses=[
        _resp("thinking...", tool_calls=[_tool_call("echo", {"q": "x"})]),
        _resp("final answer"),
    ])
    agent = _make_agent(llm, tool_registry=registry)
    agent.step_trace = StepTraceRecorder()
    text, usage = await agent._react_loop(_make_request("use the tool"))
    assert text == "final answer"
    steps = agent.step_trace.snapshot()
    kinds = [s["type"] for s in steps]
    assert kinds == ["model_invocation", "tool_invocation", "model_invocation"]
    # model step: io + usage đầy đủ
    m0 = steps[0]
    assert m0["usage"] == {"input_tokens": 10, "output_tokens": 5}
    assert m0["output"]["tool_calls"] == [{"tool": "echo", "args": "{'q': 'x'}"}]
    assert m0["input"]["round"] == 1 and m0["duration_ms"] >= 0
    # tool step: input args + output head
    t1 = steps[1]
    assert t1["input"]["tool"] == "echo" and "tool says hi" in t1["output"]["result_head"]
    # json-safe
    import json as _json
    _json.dumps(steps)


@pytest.mark.anyio
async def test_react_loop_without_recorder_records_nothing() -> None:
    llm = FakeLLMProvider(responses=[_resp("done")])
    agent = _make_agent(llm)
    assert agent.step_trace is None
    text, _ = await agent._react_loop(_make_request("q"))
    assert text == "done"
