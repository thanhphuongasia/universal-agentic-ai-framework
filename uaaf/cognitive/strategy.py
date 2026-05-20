"""ICognitiveStrategy Protocol + supporting types — P1-T02."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from uaaf.cognitive.verifier import IVerifier as IVerifier
from uaaf.cognitive.verifier import VerificationResult as VerificationResult
from uaaf.execution.agent import AgentResult, Task
from uaaf.intent.models import CognitiveResult, CostEstimate, StructuredIntent
from uaaf_workflow.context import ExecutionContext

# ---------------------------------------------------------------------------
# IAgentPool
# ---------------------------------------------------------------------------


@runtime_checkable
class IAgentPool(Protocol):
    """Dispatches tasks to available agents and returns their results."""

    async def dispatch(self, task: Task) -> AgentResult: ...


# ---------------------------------------------------------------------------
# ICognitiveStrategy
# ---------------------------------------------------------------------------


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
