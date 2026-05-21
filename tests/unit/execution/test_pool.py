"""Tests for ryuu.execution.pool — P6-T01 + P6-T02."""

from __future__ import annotations

from dataclasses import dataclass

import anyio
import pytest

from ryuu.cognitive.strategy import IAgentPool
from ryuu.execution.agent import AgentResult, BaseAgent, Task
from ryuu.execution.pool import AgentPool
from ryuu.observability.audit import AuditConfig, AuditLogger
from ryuu.observability.cost import Cost, CostPolicy, CostTracker
from ryuu.observability.rate_limit import RateLimiter, RatePolicy
from ryuu.observability.tracer import Tracer
from ryuu_workflow.context import ContextScope, ExecutionContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tracer() -> Tracer:
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    return Tracer(service_name="test", exporter=InMemorySpanExporter())


def _make_context(suffix: str = "s1") -> ExecutionContext:
    return ExecutionContext(
        scope=ContextScope(user_id="u1", session_id=suffix, domain="test"),
        correlation_id="corr-pool-test",
    )


@dataclass
class SimpleAgent(BaseAgent):
    output: str = "ok"
    raise_exc: Exception | None = None

    async def _execute(self, task: Task, context: ExecutionContext) -> AgentResult:
        if self.raise_exc is not None:
            raise self.raise_exc
        return AgentResult(task_id=task.task_id, output=self.output, cost=Cost.zero())


def _make_agent(
    agent_id: str,
    *,
    output: str = "ok",
    raise_exc: Exception | None = None,
    rps: float = 10_000.0,
) -> SimpleAgent:
    return SimpleAgent(
        agent_id=agent_id,
        cost_tracker=CostTracker(CostPolicy()),
        tracer=_make_tracer(),
        audit_logger=AuditLogger(AuditConfig(backend="console")),
        rate_limiter=RateLimiter(RatePolicy(rps=rps, burst=1000)),
        output=output,
        raise_exc=raise_exc,
    )


def _make_task(task_id: str = "t1") -> Task:
    return Task(task_id=task_id, payload={})


# ---------------------------------------------------------------------------
# register / query
# ---------------------------------------------------------------------------


def test_register_and_agent_ids() -> None:
    pool = AgentPool()
    a = _make_agent("a")
    b = _make_agent("b")
    pool.register(a)
    pool.register(b)
    assert pool.agent_ids() == ["a", "b"]


def test_agents_with_tag_returns_matching() -> None:
    pool = AgentPool()
    pool.register(_make_agent("nlp1"), tags={"nlp", "fast"})
    pool.register(_make_agent("nlp2"), tags={"nlp"})
    pool.register(_make_agent("vision"), tags={"vision"})

    nlp = pool.agents_with_tag("nlp")
    assert len(nlp) == 2
    assert {a.agent_id for a in nlp} == {"nlp1", "nlp2"}


def test_agents_with_tag_no_match_returns_empty() -> None:
    pool = AgentPool()
    pool.register(_make_agent("a"), tags={"nlp"})
    assert pool.agents_with_tag("vision") == []


# ---------------------------------------------------------------------------
# dispatch — round_robin
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_dispatch_round_robin_cycles() -> None:
    pool = AgentPool()
    for name in ("w0", "w1", "w2"):
        pool.register(_make_agent(name, output=name))

    ctx = _make_context()
    dispatched: list[str] = []
    for i in range(5):
        result = await pool.dispatch(Task(task_id=f"t{i}", payload={}), ctx)
        dispatched.append(result.output)

    assert dispatched == ["w0", "w1", "w2", "w0", "w1"]


@pytest.mark.anyio
async def test_dispatch_random_returns_a_result() -> None:
    pool = AgentPool()
    pool.register(_make_agent("a", output="from-a"))
    pool.register(_make_agent("b", output="from-b"))

    ctx = _make_context()
    result = await pool.dispatch(_make_task(), ctx, strategy="random")
    assert result.output in {"from-a", "from-b"}


@pytest.mark.anyio
async def test_dispatch_empty_pool_raises_value_error() -> None:
    pool = AgentPool()
    with pytest.raises(ValueError, match="no agents"):
        await pool.dispatch(_make_task(), _make_context())


# ---------------------------------------------------------------------------
# dispatch_to
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_dispatch_to_known_agent_returns_result() -> None:
    pool = AgentPool()
    pool.register(_make_agent("target", output="from-target"))
    pool.register(_make_agent("other", output="from-other"))

    result = await pool.dispatch_to("target", _make_task(), _make_context())
    assert result.output == "from-target"


@pytest.mark.anyio
async def test_dispatch_to_unknown_agent_raises_key_error() -> None:
    pool = AgentPool()
    pool.register(_make_agent("a"))
    with pytest.raises(KeyError, match="not registered"):
        await pool.dispatch_to("unknown", _make_task(), _make_context())


# ---------------------------------------------------------------------------
# fan_out — basic
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_fan_out_empty_tasks_returns_empty() -> None:
    pool = AgentPool()
    pool.register(_make_agent("w0"))
    results = await pool.fan_out([], _make_context())
    assert results == []


@pytest.mark.anyio
async def test_fan_out_results_are_ordered_by_input() -> None:
    pool = AgentPool()
    pool.register(_make_agent("w0", output="w0"))
    pool.register(_make_agent("w1", output="w1"))

    tasks = [Task(task_id=f"t{i}", payload={}) for i in range(6)]
    results = await pool.fan_out(tasks, _make_context())

    assert len(results) == 6
    assert [r.task_id for r in results] == [f"t{i}" for i in range(6)]


@pytest.mark.anyio
async def test_fan_out_bounded_concurrency() -> None:
    """Verify that at most max_concurrency=2 tasks run simultaneously."""
    import asyncio as _asyncio

    concurrent_peak = 0
    running = 0
    lock = _asyncio.Lock()

    @dataclass
    class CountingAgent(BaseAgent):
        async def _execute(self, task: Task, context: ExecutionContext) -> AgentResult:
            nonlocal concurrent_peak, running
            async with lock:
                running += 1
                concurrent_peak = max(concurrent_peak, running)
            await anyio.sleep(0.01)
            async with lock:
                running -= 1
            return AgentResult(task_id=task.task_id, output="ok", cost=Cost.zero())

    agent = CountingAgent(
        agent_id="counting",
        cost_tracker=CostTracker(CostPolicy()),
        tracer=_make_tracer(),
        audit_logger=AuditLogger(AuditConfig(backend="console")),
        rate_limiter=RateLimiter(RatePolicy(rps=10_000.0, burst=1000)),
    )

    pool = AgentPool(max_concurrency=2)
    pool.register(agent)

    tasks = [Task(task_id=f"t{i}", payload={}) for i in range(5)]
    await pool.fan_out(tasks, _make_context())

    assert concurrent_peak <= 2


@pytest.mark.anyio
async def test_fan_out_tag_filter_dispatches_to_matching_agents_only() -> None:
    pool = AgentPool()
    pool.register(_make_agent("nlp", output="nlp-result"), tags={"nlp"})
    pool.register(_make_agent("vision", output="vision-result"), tags={"vision"})

    tasks = [Task(task_id=f"t{i}", payload={}) for i in range(3)]
    results = await pool.fan_out(tasks, _make_context(), tag_filter="nlp")

    assert all(r.output == "nlp-result" for r in results)


@pytest.mark.anyio
async def test_fan_out_no_agents_for_tag_raises_value_error() -> None:
    pool = AgentPool()
    pool.register(_make_agent("a"), tags={"nlp"})
    with pytest.raises(ValueError, match="no agents"):
        await pool.fan_out([_make_task()], _make_context(), tag_filter="vision")


# ---------------------------------------------------------------------------
# fan_out — fail_fast (default)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_fan_out_fail_fast_raises_on_worker_error() -> None:
    pool = AgentPool()
    pool.register(_make_agent("ok", output="ok"))
    pool.register(_make_agent("bad", raise_exc=RuntimeError("boom")))

    tasks = [Task(task_id=f"t{i}", payload={}) for i in range(4)]
    with pytest.raises(ExceptionGroup):
        await pool.fan_out(tasks, _make_context(), on_error="fail_fast")


# ---------------------------------------------------------------------------
# fan_out — collect mode
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_fan_out_collect_returns_all_results_including_failures() -> None:
    pool = AgentPool()
    pool.register(_make_agent("ok", output="good"))
    pool.register(_make_agent("bad", raise_exc=RuntimeError("boom")))

    tasks = [Task(task_id=f"t{i}", payload={}) for i in range(4)]
    results = await pool.fan_out(tasks, _make_context(), on_error="collect")

    assert len(results) == 4

    failures = [r for r in results if not r.success]
    successes = [r for r in results if r.success]

    assert len(failures) >= 1
    assert len(successes) >= 1
    assert all("error" in r.metadata for r in failures)


@pytest.mark.anyio
async def test_fan_out_collect_all_succeed() -> None:
    pool = AgentPool()
    pool.register(_make_agent("w0", output="ok"))

    tasks = [Task(task_id=f"t{i}", payload={}) for i in range(3)]
    results = await pool.fan_out(tasks, _make_context(), on_error="collect")

    assert len(results) == 3
    assert all(r.success for r in results)


@pytest.mark.anyio
async def test_fan_out_collect_failure_has_error_metadata() -> None:
    pool = AgentPool()
    pool.register(_make_agent("bad", raise_exc=ValueError("bad input")))

    results = await pool.fan_out([_make_task()], _make_context(), on_error="collect")

    assert len(results) == 1
    assert results[0].success is False
    # BaseAgent wraps unexpected exceptions in FatalError — error key must exist
    assert "error" in results[0].metadata
    assert len(results[0].metadata["error"]) > 0


# ---------------------------------------------------------------------------
# IAgentPool protocol compliance
# ---------------------------------------------------------------------------


def test_agent_pool_satisfies_iagentpool_protocol() -> None:
    pool = AgentPool()
    assert isinstance(pool, IAgentPool)


# ---------------------------------------------------------------------------
# rate-limiter × max_concurrency — no deadlock (Fix #8)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_fan_out_rate_limiter_saturation_no_deadlock() -> None:
    """fan_out với max_concurrency > rps budget → không deadlock.

    Workers có rps=100 (không quá thấp để test không chậm), max_concurrency=8.
    Verify rằng fan_out hoàn thành trong thời gian bounded.
    """
    pool = AgentPool(max_concurrency=8)
    for i in range(3):
        pool.register(_make_agent(f"w{i}", output="ok", rps=100.0))

    tasks = [Task(task_id=f"t{i}", payload={}) for i in range(8)]

    with anyio.fail_after(10.0):
        results = await pool.fan_out(tasks, _make_context())

    assert len(results) == 8
    assert all(r.success for r in results)


# ---------------------------------------------------------------------------
# dispatch — no context arg uses fallback context (coverage pool.py:193)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_dispatch_without_context_uses_fallback() -> None:
    pool = AgentPool()
    pool.register(_make_agent("w0", output="fallback-ok"))
    result = await pool.dispatch(_make_task())  # no context → _fallback_context()
    assert result.output == "fallback-ok"
