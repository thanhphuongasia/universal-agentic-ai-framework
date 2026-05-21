"""ParallelFanoutStrategy — decompose → fan_out → aggregate → verify."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ryuu_cognitive.strategy import IAgentPool, IVerifier
from ryuu_core.context import ExecutionContext
from ryuu_core.models import (
    PARALLEL_FANOUT,
    AgentResult,
    CognitiveResult,
    ComplexityLevel,
    CostEstimate,
    StructuredIntent,
    Task,
)

if TYPE_CHECKING:
    pass


@runtime_checkable
class ISubtaskBuilder(Protocol):
    """Decomposes a StructuredIntent into a list of Tasks for parallel dispatch."""

    def build_subtasks(
        self, intent: StructuredIntent, context: ExecutionContext
    ) -> list[Task]: ...


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


@dataclass
class ParallelFanoutStrategy:
    """Parallel fan-out: decompose → fan_out workers → aggregate → verify."""

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
            return CognitiveResult(content="", confidence=0.0, strategy_id=PARALLEL_FANOUT)

        results: list[AgentResult]
        if hasattr(agent_pool, "fan_out"):
            results = await agent_pool.fan_out(subtasks, context, on_error="collect")
        else:
            results = [await agent_pool.dispatch(task) for task in subtasks]

        combined = "\n\n".join(
            str(r.output) for r in results if r.success and r.output is not None
        )

        verification = await verifier.verify(combined, context)
        confidence = (
            verification.confidence if verification.passed else 0.5 * verification.confidence
        )

        return CognitiveResult(content=combined, confidence=confidence, strategy_id=PARALLEL_FANOUT)
