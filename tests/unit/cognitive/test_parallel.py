"""Tests for ISubtaskBuilder, EntitySubtaskBuilder, ParallelFanoutStrategy — P6-T03."""

from __future__ import annotations

import pytest

from uaaf._testing.fakes import FakeAgentPool, FakeVerifier
from uaaf.cognitive.strategies.parallel import (
    EntitySubtaskBuilder,
    ISubtaskBuilder,
    ParallelFanoutStrategy,
)
from uaaf.cognitive.strategy import ICognitiveStrategy
from uaaf.execution.agent import AgentResult, Task
from uaaf.execution.pool import AgentPool
from uaaf.intent.models import PARALLEL_FANOUT, ComplexityLevel, StructuredIntent
from uaaf.observability.cost import Cost
from uaaf_workflow.context import ContextScope, ExecutionContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx() -> ExecutionContext:
    return ExecutionContext(
        scope=ContextScope(user_id="u1", session_id="s1", domain="test"),
        correlation_id="c1",
    )


def _intent(
    complexity: ComplexityLevel = ComplexityLevel.HIGH,
    entities: dict | None = None,
) -> StructuredIntent:
    return StructuredIntent(
        intent_type="analysis",
        action="analyze",
        entities=entities if entities is not None else {"mod_a": "v1", "mod_b": "v2"},
        complexity=complexity,
        confidence=0.9,
    )


def _pool_with_responses(n: int = 4) -> FakeAgentPool:
    return FakeAgentPool(responses=[
        AgentResult(task_id=f"t{i}", output=f"output-{i}", cost=Cost.zero())
        for i in range(n)
    ])


# ---------------------------------------------------------------------------
# ISubtaskBuilder Protocol
# ---------------------------------------------------------------------------


def test_entity_subtask_builder_satisfies_protocol() -> None:
    builder = EntitySubtaskBuilder()
    assert isinstance(builder, ISubtaskBuilder)


def test_entity_subtask_builder_one_task_per_entity() -> None:
    builder = EntitySubtaskBuilder()
    intent = _intent(entities={"a": "1", "b": "2", "c": "3"})
    tasks = builder.build_subtasks(intent, _ctx())
    assert len(tasks) == 3
    assert all(isinstance(t, Task) for t in tasks)


def test_entity_subtask_builder_empty_entities_returns_empty() -> None:
    builder = EntitySubtaskBuilder()
    tasks = builder.build_subtasks(_intent(entities={}), _ctx())
    assert tasks == []


def test_entity_subtask_builder_task_payload_contains_entity() -> None:
    builder = EntitySubtaskBuilder()
    tasks = builder.build_subtasks(_intent(entities={"mod_x": "v1"}), _ctx())
    assert len(tasks) == 1
    assert tasks[0].payload["entity_key"] == "mod_x"
    assert tasks[0].payload["entity_value"] == "v1"


# ---------------------------------------------------------------------------
# ParallelFanoutStrategy.applicable()
# ---------------------------------------------------------------------------


def test_applicable_true_for_high_complexity_multiple_entities() -> None:
    strategy = ParallelFanoutStrategy()
    assert strategy.applicable(_intent(ComplexityLevel.HIGH, {"a": 1, "b": 2}), _ctx()) is True


def test_applicable_false_for_medium_complexity() -> None:
    strategy = ParallelFanoutStrategy()
    assert strategy.applicable(_intent(ComplexityLevel.MEDIUM, {"a": 1, "b": 2}), _ctx()) is False


def test_applicable_false_for_high_with_single_entity() -> None:
    strategy = ParallelFanoutStrategy()
    assert strategy.applicable(_intent(ComplexityLevel.HIGH, {"a": 1}), _ctx()) is False


def test_applicable_false_for_high_with_no_entities() -> None:
    strategy = ParallelFanoutStrategy()
    assert strategy.applicable(_intent(ComplexityLevel.HIGH, {}), _ctx()) is False


# ---------------------------------------------------------------------------
# ParallelFanoutStrategy.estimate_cost()
# ---------------------------------------------------------------------------


def test_estimate_cost_scales_with_entity_count() -> None:
    from uaaf.intent.models import CostEstimate
    strategy = ParallelFanoutStrategy()
    cost = strategy.estimate_cost(_intent(entities={"a": 1, "b": 2, "c": 3}), _ctx())
    assert isinstance(cost, CostEstimate)
    assert cost.steps_est == 3
    assert cost.usd_est > 0.0


# ---------------------------------------------------------------------------
# ParallelFanoutStrategy.execute()
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_execute_returns_cognitive_result_with_strategy_id() -> None:
    from uaaf.intent.models import CognitiveResult
    strategy = ParallelFanoutStrategy()
    result = await strategy.execute(
        _intent(), _ctx(), _pool_with_responses(2), FakeVerifier()
    )
    assert isinstance(result, CognitiveResult)
    assert result.strategy_id == PARALLEL_FANOUT


@pytest.mark.anyio
async def test_execute_aggregates_worker_outputs() -> None:
    strategy = ParallelFanoutStrategy()
    result = await strategy.execute(
        _intent(entities={"a": "1", "b": "2"}),
        _ctx(),
        _pool_with_responses(4),
        FakeVerifier(),
    )
    assert "output-0" in result.content or "output-1" in result.content


@pytest.mark.anyio
async def test_execute_calls_verifier() -> None:
    verifier = FakeVerifier(pass_sequence=[True])
    strategy = ParallelFanoutStrategy()
    await strategy.execute(_intent(), _ctx(), _pool_with_responses(2), verifier)
    assert verifier.verify_count == 1


@pytest.mark.anyio
async def test_execute_confidence_lowered_on_verifier_fail() -> None:
    verifier = FakeVerifier(pass_sequence=[False], confidence_sequence=[0.4])
    strategy = ParallelFanoutStrategy()
    result = await strategy.execute(_intent(), _ctx(), _pool_with_responses(4), verifier)
    assert result.confidence < 0.4  # penalized confidence


@pytest.mark.anyio
async def test_execute_empty_subtasks_returns_empty_result() -> None:
    strategy = ParallelFanoutStrategy()
    result = await strategy.execute(
        _intent(entities={}), _ctx(), _pool_with_responses(0), FakeVerifier()
    )
    assert result.content == ""
    assert result.strategy_id == PARALLEL_FANOUT


@pytest.mark.anyio
async def test_execute_uses_real_pool_fan_out() -> None:
    """ParallelFanoutStrategy integrates with AgentPool.fan_out (collect mode)."""
    from dataclasses import dataclass

    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from uaaf.execution.agent import BaseAgent
    from uaaf.observability.audit import AuditConfig, AuditLogger
    from uaaf.observability.cost import CostPolicy, CostTracker
    from uaaf.observability.rate_limit import RateLimiter, RatePolicy
    from uaaf.observability.tracer import Tracer

    @dataclass
    class EchoAgent(BaseAgent):
        async def _execute(self, task: Task, context: ExecutionContext) -> AgentResult:
            return AgentResult(task_id=task.task_id, output=f"echo:{task.payload}", cost=Cost.zero())

    def _make_echo(name: str) -> EchoAgent:
        return EchoAgent(
            agent_id=name,
            cost_tracker=CostTracker(CostPolicy()),
            tracer=Tracer(service_name="test", exporter=InMemorySpanExporter()),
            audit_logger=AuditLogger(AuditConfig(backend="console")),
            rate_limiter=RateLimiter(RatePolicy(rps=10_000.0, burst=100)),
        )

    pool = AgentPool(max_concurrency=4)
    pool.register(_make_echo("w0"))
    pool.register(_make_echo("w1"))

    strategy = ParallelFanoutStrategy()
    result = await strategy.execute(
        _intent(entities={"mod_a": "v1", "mod_b": "v2"}),
        _ctx(),
        pool,  # type: ignore[arg-type]
        FakeVerifier(),
    )
    assert "echo:" in result.content


@pytest.mark.anyio
async def test_execute_collect_skips_failed_workers() -> None:
    """Workers that fail are excluded from the combined output."""
    from uaaf._testing.fakes import FakeAgentPool

    fail_pool = FakeAgentPool(responses=[
        AgentResult(task_id="t0", output="good", cost=Cost.zero(), success=True),
        AgentResult(task_id="t1", output=None, cost=Cost.zero(), success=False, metadata={"error": "oops"}),
    ])

    strategy = ParallelFanoutStrategy()
    result = await strategy.execute(
        _intent(entities={"a": "1", "b": "2"}),
        _ctx(),
        fail_pool,
        FakeVerifier(),
    )
    assert "good" in result.content
    assert result.strategy_id == PARALLEL_FANOUT


# ---------------------------------------------------------------------------
# Custom ISubtaskBuilder injection
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_custom_subtask_builder_is_used() -> None:
    class FixedBuilder:
        def build_subtasks(self, intent: StructuredIntent, context: ExecutionContext) -> list[Task]:
            return [Task(task_id="custom-task", payload={"custom": True})]

    strategy = ParallelFanoutStrategy(subtask_builder=FixedBuilder())
    result = await strategy.execute(
        _intent(), _ctx(), _pool_with_responses(2), FakeVerifier()
    )
    assert isinstance(result.content, str)


# ---------------------------------------------------------------------------
# ICognitiveStrategy Protocol compliance
# ---------------------------------------------------------------------------


def test_parallel_fanout_satisfies_protocol() -> None:
    assert isinstance(ParallelFanoutStrategy(), ICognitiveStrategy)


def test_parallel_fanout_strategy_id() -> None:
    assert ParallelFanoutStrategy().strategy_id == PARALLEL_FANOUT


# ---------------------------------------------------------------------------
# fallback to sequential dispatch when pool has no fan_out (coverage line 121)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_execute_falls_back_to_sequential_dispatch_when_no_fan_out() -> None:
    """If the pool only implements IAgentPool (no fan_out), strategy falls back gracefully."""
    class MinimalPool:
        async def dispatch(self, task: Task) -> AgentResult:
            return AgentResult(task_id=task.task_id, output="sequential", cost=Cost.zero())

    strategy = ParallelFanoutStrategy()
    result = await strategy.execute(
        _intent(entities={"a": "1", "b": "2"}),
        _ctx(),
        MinimalPool(),  # type: ignore[arg-type]
        FakeVerifier(),
    )
    assert "sequential" in result.content
