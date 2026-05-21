"""ICognitiveStrategy Protocol + IAgentPool Protocol."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ryuu_cognitive.verifier import IVerifier as IVerifier
from ryuu_cognitive.verifier import VerificationResult as VerificationResult
from ryuu_core.context import ExecutionContext
from ryuu_core.models import AgentResult, CognitiveResult, CostEstimate, StructuredIntent, Task


@runtime_checkable
class IAgentPool(Protocol):
    """Dispatches tasks to available agents and returns their results."""

    async def dispatch(self, task: Task) -> AgentResult: ...


@runtime_checkable
class ICognitiveStrategy(Protocol):
    """Orchestrates LLM calls to satisfy a StructuredIntent."""

    strategy_id: str

    def applicable(self, intent: StructuredIntent, context: ExecutionContext) -> bool: ...

    def estimate_cost(
        self, intent: StructuredIntent, context: ExecutionContext
    ) -> CostEstimate: ...

    async def execute(
        self,
        intent: StructuredIntent,
        context: ExecutionContext,
        agent_pool: IAgentPool,
        verifier: IVerifier,
    ) -> CognitiveResult: ...
