"""ParallelFanoutStrategy — ICognitiveStrategy #4.

Decomposes a HIGH-complexity intent into N subtasks (one per entity),
dispatches them in parallel via AgentPool.fan_out(on_error="collect"),
aggregates successful outputs, then verifies the combined result.

Design:
- Uses on_error="collect" so 1 worker failure doesn't abort other workers.
- Falls back to sequential dispatch() if the pool doesn't support fan_out
  (for backward compat with IAgentPool-only implementations).
- ISubtaskBuilder is injected — default is EntitySubtaskBuilder (1 task per entity).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from uaaf.cognitive.strategy import IAgentPool, IVerifier
from uaaf.execution.agent import AgentResult, Task
from uaaf.intent.models import (
    PARALLEL_FANOUT,
    CognitiveResult,
    ComplexityLevel,
    CostEstimate,
    StructuredIntent,
)
from uaaf.runtime.context import ExecutionContext

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# ISubtaskBuilder Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ISubtaskBuilder(Protocol):
    """Decomposes a StructuredIntent into a list of Tasks for parallel dispatch."""

    def build_subtasks(
        self, intent: StructuredIntent, context: ExecutionContext
    ) -> list[Task]: ...


# ---------------------------------------------------------------------------
# Default implementation
# ---------------------------------------------------------------------------


@dataclass
class EntitySubtaskBuilder:
    """Default ISubtaskBuilder: produces one task per entity in intent.entities."""

    def build_subtasks(
        self, intent: StructuredIntent, context: ExecutionContext
    ) -> list[Task]:
        return [
            Task(
                task_id=f"subtask-{key}",
                payload={"entity_key": key, "entity_value": val},
            )
            for key, val in intent.entities.items()
        ]


# ---------------------------------------------------------------------------
# ParallelFanoutStrategy
# ---------------------------------------------------------------------------


@dataclass
class ParallelFanoutStrategy:
    """Parallel fan-out strategy: decompose → fan_out workers → aggregate → verify.

    Applicable when complexity=HIGH and intent has more than one entity.
    Each entity maps to one subtask dispatched to an independent worker agent.
    """

    strategy_id: str = PARALLEL_FANOUT
    subtask_builder: ISubtaskBuilder = field(default_factory=EntitySubtaskBuilder)

    def applicable(self, intent: StructuredIntent, context: ExecutionContext) -> bool:
        return intent.complexity == ComplexityLevel.HIGH and len(intent.entities) > 1

    def estimate_cost(
        self, intent: StructuredIntent, context: ExecutionContext
    ) -> CostEstimate:
        n = max(len(intent.entities), 1)
        return CostEstimate(
            input_tokens_est=500 * n,
            output_tokens_est=200 * n,
            usd_est=round(0.0001 * n, 6),
            steps_est=n,
        )

    async def execute(
        self,
        intent: StructuredIntent,
        context: ExecutionContext,
        agent_pool: IAgentPool,
        verifier: IVerifier,
    ) -> CognitiveResult:
        subtasks = self.subtask_builder.build_subtasks(intent, context)

        if not subtasks:
            return CognitiveResult(
                content="",
                confidence=0.0,
                strategy_id=PARALLEL_FANOUT,
            )

        # Prefer fan_out (collect mode) for concurrent dispatch with partial failure support.
        # Fall back to sequential dispatch for IAgentPool-only implementations.
        results: list[AgentResult]
        if hasattr(agent_pool, "fan_out"):
            results = await agent_pool.fan_out(subtasks, context, on_error="collect")
        else:
            results = [await agent_pool.dispatch(task) for task in subtasks]

        # Aggregate only successful worker outputs
        combined = "\n\n".join(
            str(r.output) for r in results if r.success and r.output is not None
        )

        verification = await verifier.verify(combined, context)
        confidence = (
            verification.confidence
            if verification.passed
            else 0.5 * verification.confidence
        )

        return CognitiveResult(
            content=combined,
            confidence=confidence,
            strategy_id=PARALLEL_FANOUT,
        )
