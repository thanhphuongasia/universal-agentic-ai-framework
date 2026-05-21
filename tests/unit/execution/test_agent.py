"""Tests for ryuu.execution.agent (BaseAgent template method) — T08."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from ryuu.execution.agent import AgentResult, BaseAgent, Task
from ryuu.observability.audit import AuditConfig, AuditLogger
from ryuu.observability.cost import Cost, CostPolicy, CostTracker
from ryuu_workflow.errors import (
    BudgetExceededError,
    DegradedError,
    FatalError,
    RetryableError,
)
from ryuu.observability.rate_limit import RateLimiter, RatePolicy
from ryuu.observability.tracer import Tracer
from ryuu_workflow.context import ContextScope, ExecutionContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tracer() -> Tracer:
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    return Tracer(service_name="test", exporter=InMemorySpanExporter())


def _make_context(scope_key_suffix: str = "s1") -> ExecutionContext:
    scope = ContextScope(user_id="u1", session_id=scope_key_suffix, domain="test")
    return ExecutionContext(scope=scope, correlation_id="corr-test")


def _make_agent(
    agent_id: str = "test-agent",
    *,
    policy: CostPolicy | None = None,
    rate_policy: RatePolicy | None = None,
    raise_exc: Exception | None = None,
    return_cost: Cost | None = None,
) -> SimpleAgent:
    return SimpleAgent(
        agent_id=agent_id,
        cost_tracker=CostTracker(policy=policy or CostPolicy()),
        tracer=_make_tracer(),
        audit_logger=AuditLogger(AuditConfig(backend="console")),
        rate_limiter=RateLimiter(policy=rate_policy or RatePolicy(rps=1000.0, burst=100)),
        raise_exc=raise_exc,
        return_cost=return_cost or Cost.zero(provider="fake", model="fake"),
    )


@dataclass
class SimpleAgent(BaseAgent):
    """Minimal agent for testing the BaseAgent template."""

    raise_exc: Exception | None = None
    return_cost: Cost = Cost(input_tokens=5, output_tokens=5, usd=0.001, provider="fake", model="fake")  # type: ignore[assignment]

    async def _execute(self, task: Task, context: ExecutionContext) -> AgentResult:
        if self.raise_exc is not None:
            raise self.raise_exc
        return AgentResult(
            task_id=task.task_id,
            output=task.payload.get("msg", "done"),
            cost=self.return_cost,
        )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_execute_returns_agent_result() -> None:
    agent = _make_agent()
    ctx = _make_context()
    result = await agent.execute(Task(task_id="t1", payload={"msg": "hello"}), ctx)
    assert result.task_id == "t1"
    assert result.output == "hello"
    assert result.success is True


@pytest.mark.anyio
async def test_execute_records_cost(capsys: pytest.CaptureFixture[str]) -> None:
    cost = Cost(input_tokens=20, output_tokens=10, usd=0.005, provider="fake", model="fake")
    agent = _make_agent(return_cost=cost)
    ctx = _make_context()
    await agent.execute(Task(task_id="t1", payload={}), ctx)
    snap = agent.cost_tracker.get_usage(ctx.scope.scope_key)
    assert abs(snap.total_usd - 0.005) < 1e-9


# ---------------------------------------------------------------------------
# Cross-cutting: audit
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_execute_audits_start_and_complete(capsys: pytest.CaptureFixture[str]) -> None:
    import json

    agent = _make_agent()
    ctx = _make_context()
    await agent.execute(Task(task_id="audit-task", payload={}), ctx)
    out = capsys.readouterr().err
    events = [json.loads(line) for line in out.strip().splitlines() if line]
    event_types = [e["event_type"] for e in events]
    assert "start" in event_types
    assert "complete" in event_types


# ---------------------------------------------------------------------------
# Cross-cutting: error tier handling
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_retryable_error_propagates_as_is() -> None:
    agent = _make_agent(raise_exc=RetryableError("transient"))
    with pytest.raises(RetryableError):
        await agent.execute(Task(task_id="t1", payload={}), _make_context())


@pytest.mark.anyio
async def test_degraded_error_propagates_as_is() -> None:
    agent = _make_agent(raise_exc=DegradedError("degraded"))
    with pytest.raises(DegradedError):
        await agent.execute(Task(task_id="t1", payload={}), _make_context())


@pytest.mark.anyio
async def test_unexpected_exception_wrapped_as_fatal() -> None:
    agent = _make_agent(raise_exc=ValueError("unexpected"))
    with pytest.raises(FatalError):
        await agent.execute(Task(task_id="t1", payload={}), _make_context())


@pytest.mark.anyio
async def test_unexpected_exception_preserves_cause() -> None:
    orig = ValueError("root cause")
    agent = _make_agent(raise_exc=orig)
    with pytest.raises(FatalError) as exc_info:
        await agent.execute(Task(task_id="t1", payload={}), _make_context())
    assert exc_info.value.__cause__ is orig


# ---------------------------------------------------------------------------
# Cross-cutting: budget enforcement
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_over_budget_raises_budget_exceeded_before_execute() -> None:
    policy = CostPolicy(per_user_per_day_usd=0.001)
    # Seed existing usage near the cap
    tracker = CostTracker(policy=policy)
    scope = ContextScope(user_id="u", session_id="s", domain="d")
    tracker.record(scope.scope_key, Cost(10, 5, 0.0009, "fake", "fake"))

    agent = SimpleAgent(
        agent_id="budget-test",
        cost_tracker=tracker,
        tracer=_make_tracer(),
        audit_logger=AuditLogger(AuditConfig(backend="console")),
        rate_limiter=RateLimiter(RatePolicy(rps=1000, burst=100)),
        raise_exc=None,
        return_cost=Cost.zero(),
    )
    ctx = ExecutionContext(scope=scope, correlation_id="c")
    # estimated cost exceeds remaining budget
    task = Task(
        task_id="t",
        payload={},
        estimated_cost=Cost(10, 5, 0.002, "fake", "fake"),
    )
    with pytest.raises(BudgetExceededError):
        await agent.execute(task, ctx)


# ---------------------------------------------------------------------------
# Cross-cutting: span nesting
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_span_has_correct_correlation_id() -> None:
    from ryuu.observability.tracer import get_current_correlation_id

    captured: list[str | None] = []

    @dataclass
    class SpanCapturingAgent(BaseAgent):
        async def _execute(self, task: Task, context: ExecutionContext) -> AgentResult:
            captured.append(get_current_correlation_id())
            return AgentResult(task_id=task.task_id, output="ok", cost=Cost.zero())

    agent = SpanCapturingAgent(
        agent_id="spy",
        cost_tracker=CostTracker(),
        tracer=_make_tracer(),
        audit_logger=AuditLogger(AuditConfig(backend="console")),
        rate_limiter=RateLimiter(RatePolicy(rps=1000, burst=100)),
    )
    ctx = ExecutionContext(
        scope=ContextScope(user_id="u", session_id="s", domain="d"),
        correlation_id="my-corr-id",
    )
    await agent.execute(Task(task_id="t", payload={}), ctx)
    assert captured[0] == "my-corr-id"


# ---------------------------------------------------------------------------
# enforce_cognitive_routing — P7-T10
# ---------------------------------------------------------------------------

import dataclasses  # noqa: E402


class TestEnforceCognitiveRouting:
    @pytest.mark.asyncio
    async def test_enforce_false_allows_direct_call(self):
        """Default (False): execute() without strategy_id proceeds normally."""
        agent = _make_agent()
        ctx = _make_context()
        assert ctx.strategy_id is None
        result = await agent.execute(Task(task_id="t", payload={}), ctx)
        assert result is not None  # proceeds normally — no RuntimeError

    @pytest.mark.asyncio
    async def test_enforce_true_raises_without_strategy_id(self):
        """enforce=True: execute() without strategy_id raises RuntimeError."""

        @dataclass
        class StrictAgent(BaseAgent):
            enforce_cognitive_routing: bool = True

            async def _execute(self, task: Task, context: ExecutionContext) -> AgentResult:
                return AgentResult(task_id=task.task_id, output="ok", cost=Cost.zero())

        agent = StrictAgent(
            agent_id="strict",
            cost_tracker=CostTracker(),
            tracer=_make_tracer(),
            audit_logger=AuditLogger(AuditConfig(backend="console")),
            rate_limiter=RateLimiter(RatePolicy(rps=1000, burst=100)),
        )
        ctx = _make_context()
        assert ctx.strategy_id is None
        with pytest.raises(RuntimeError, match="cognitive routing"):
            await agent.execute(Task(task_id="t", payload={}), ctx)

    @pytest.mark.asyncio
    async def test_enforce_true_allows_call_with_strategy_id(self):
        """enforce=True: execute() with strategy_id set proceeds normally."""

        @dataclass
        class StrictAgent(BaseAgent):
            enforce_cognitive_routing: bool = True

            async def _execute(self, task: Task, context: ExecutionContext) -> AgentResult:
                return AgentResult(task_id=task.task_id, output="routed", cost=Cost.zero())

        agent = StrictAgent(
            agent_id="strict",
            cost_tracker=CostTracker(),
            tracer=_make_tracer(),
            audit_logger=AuditLogger(AuditConfig(backend="console")),
            rate_limiter=RateLimiter(RatePolicy(rps=1000, burst=100)),
        )
        ctx = dataclasses.replace(_make_context(), strategy_id="direct")
        result = await agent.execute(Task(task_id="t", payload={}), ctx)
        assert result.output == "routed"
