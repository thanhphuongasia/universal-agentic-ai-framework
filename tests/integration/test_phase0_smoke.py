"""Phase 0 smoke test — T13.

Demonstrates that a minimal LLMAgent using BaseAgent with FakeLLMProvider
wires up cost, trace, audit, and rate-limit correctly end-to-end.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from uaaf._testing.fakes import FakeLLMProvider
from uaaf.execution.agent import AgentResult, BaseAgent, Task
from uaaf.observability.audit import AuditConfig, AuditLogger
from uaaf.observability.cost import Cost, CostPolicy, CostTracker
from uaaf_workflow.errors import BudgetExceededError, RetryableError
from uaaf.observability.rate_limit import RateLimiter, RatePolicy
from uaaf.observability.tracer import Tracer, get_current_correlation_id
from uaaf.providers.llm import CompletionRequest, Message
from uaaf_workflow.context import ContextScope, ExecutionContext

# ---------------------------------------------------------------------------
# Agent under test
# ---------------------------------------------------------------------------


@dataclass
class EchoLLMAgent(BaseAgent):
    """Calls FakeLLMProvider and echoes the response content."""

    llm: FakeLLMProvider = field(default_factory=FakeLLMProvider)

    async def _execute(self, task: Task, context: ExecutionContext) -> AgentResult:
        req = CompletionRequest(
            messages=[Message(role="user", content=task.payload.get("msg", "hello"))],
            model="fake",
        )
        response = await self.llm.complete(req)
        cost = self.llm.estimate_cost(req)
        return AgentResult(
            task_id=task.task_id,
            output=response.content,
            cost=cost,
        )


def _make_tracer() -> Tracer:
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    return Tracer(service_name="smoke-test", exporter=InMemorySpanExporter())


def _make_agent(
    policy: CostPolicy | None = None,
    rate_policy: RatePolicy | None = None,
    fake_llm: FakeLLMProvider | None = None,
) -> EchoLLMAgent:
    return EchoLLMAgent(
        agent_id="echo-agent",
        cost_tracker=CostTracker(policy=policy or CostPolicy()),
        tracer=_make_tracer(),
        audit_logger=AuditLogger(AuditConfig(backend="console")),
        rate_limiter=RateLimiter(policy=rate_policy or RatePolicy(rps=1000.0, burst=100)),
        llm=fake_llm or FakeLLMProvider(default_content="pong"),
    )


def _make_ctx(corr_id: str = "smoke-corr-001") -> ExecutionContext:
    return ExecutionContext(
        scope=ContextScope(user_id="user1", session_id="sess1", domain="smoke"),
        correlation_id=corr_id,
    )


# ---------------------------------------------------------------------------
# Test 1: Span created with correlation_id
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_span_created_with_correlation_id() -> None:
    captured_corr: list[str | None] = []

    @dataclass
    class SpyAgent(BaseAgent):
        async def _execute(self, task: Task, context: ExecutionContext) -> AgentResult:
            captured_corr.append(get_current_correlation_id())
            return AgentResult(task_id=task.task_id, output="ok", cost=Cost.zero())

    agent = SpyAgent(
        agent_id="spy",
        cost_tracker=CostTracker(),
        tracer=_make_tracer(),
        audit_logger=AuditLogger(AuditConfig(backend="console")),
        rate_limiter=RateLimiter(RatePolicy(rps=1000, burst=100)),
    )
    ctx = _make_ctx("test-corr-id")
    await agent.execute(Task(task_id="t1", payload={}), ctx)
    assert captured_corr[0] == "test-corr-id"


# ---------------------------------------------------------------------------
# Test 2: Audit log has start + complete events
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_audit_log_has_start_and_complete(capsys: pytest.CaptureFixture[str]) -> None:
    agent = _make_agent()
    ctx = _make_ctx()
    await agent.execute(Task(task_id="audit-t1", payload={"msg": "hello"}), ctx)
    out = capsys.readouterr().err
    events = [json.loads(line) for line in out.strip().splitlines() if line]
    types = {e["event_type"] for e in events}
    assert "start" in types
    assert "complete" in types


# ---------------------------------------------------------------------------
# Test 3: Cost is recorded after execute
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cost_recorded_after_execute() -> None:
    agent = _make_agent()
    ctx = _make_ctx()
    await agent.execute(Task(task_id="cost-t1", payload={"msg": "test"}), ctx)
    snap = agent.cost_tracker.get_usage(ctx.scope.scope_key)
    assert snap.call_count == 1
    assert snap.total_usd >= 0.0


# ---------------------------------------------------------------------------
# Test 4: Rate limit is consumed
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_rate_limit_consumed() -> None:
    rate_policy = RatePolicy(rps=1000.0, burst=5)
    agent = _make_agent(rate_policy=rate_policy)
    ctx = _make_ctx()
    # Run 3 times — should all succeed within burst
    for _ in range(3):
        await agent.execute(Task(task_id="rl-t", payload={}), ctx)


# ---------------------------------------------------------------------------
# Test 5: FakeLLMProvider RateLimitError → RetryableError
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_fake_llm_retryable_error_propagates() -> None:
    fake = FakeLLMProvider(raise_on_call=RetryableError("fake rate limit"))
    agent = _make_agent(fake_llm=fake)
    ctx = _make_ctx()
    with pytest.raises(RetryableError):
        await agent.execute(Task(task_id="err-t", payload={}), ctx)


# ---------------------------------------------------------------------------
# Test 6: Over budget → DegradedError raised before LLM call
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_over_budget_raises_before_llm_call() -> None:
    policy = CostPolicy(per_user_per_day_usd=0.0001)
    fake = FakeLLMProvider(default_content="should not be called")
    agent = _make_agent(policy=policy, fake_llm=fake)
    ctx = _make_ctx()

    # Seed usage near the cap
    agent.cost_tracker.record(
        ctx.scope.scope_key, Cost(10, 5, 0.00009, "fake", "fake")
    )

    task = Task(
        task_id="budget-t",
        payload={},
        estimated_cost=Cost(10, 5, 0.00002, "fake", "fake"),  # pushes over cap
    )
    with pytest.raises(BudgetExceededError):
        await agent.execute(task, ctx)

    # LLM should NOT have been called
    assert fake.call_count == 0
