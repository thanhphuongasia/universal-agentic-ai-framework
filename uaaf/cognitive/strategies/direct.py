"""DirectStrategy — single-pass LLM call — P1-T04."""

from __future__ import annotations

from uaaf.cognitive.strategy import IAgentPool, IVerifier
from uaaf.execution.agent import Task
from uaaf.intent.models import DIRECT, CognitiveResult, CostEstimate, StructuredIntent
from uaaf_workflow.context import ExecutionContext


class DirectStrategy:
    """Satisfies an intent with a single agent dispatch. Applicable to all intents."""

    strategy_id = DIRECT

    def applicable(self, intent: StructuredIntent, context: ExecutionContext) -> bool:
        return True

    def estimate_cost(self, intent: StructuredIntent, context: ExecutionContext) -> CostEstimate:
        return CostEstimate(input_tokens_est=500, output_tokens_est=200, usd_est=0.0001, steps_est=1)

    async def execute(
        self,
        intent: StructuredIntent,
        context: ExecutionContext,
        agent_pool: IAgentPool,
        verifier: IVerifier,
    ) -> CognitiveResult:
        task = Task(
            task_id=f"direct-{context.correlation_id}",
            payload={
                "intent_type": intent.intent_type,
                "action": intent.action,
                "entities": intent.entities,
                "message": intent.action,
            },
        )
        result = await agent_pool.dispatch(task)
        return CognitiveResult(
            content=str(result.output),
            confidence=1.0,
            strategy_id=DIRECT,
        )
