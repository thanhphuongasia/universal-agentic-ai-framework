"""Todo-domain ICognitiveStrategy implementations.

TodoDirectStrategy — single-pass LLM dispatch for all todo intents.

Bridges the gap between StructuredIntent (from TodoIntentAnalyzer) and
TodoAnalysisAgent._execute() which expects payload keys "query" + "prompt".
"""

from __future__ import annotations

from uaaf.cognitive.strategy import IAgentPool, IVerifier
from uaaf.execution.agent import Task
from uaaf.execution.pool import AgentPool
from uaaf.intent.models import DIRECT, CognitiveResult, CostEstimate, StructuredIntent
from uaaf.runtime.context import ExecutionContext


class TodoDirectStrategy:
    """Satisfies any todo intent with a single agent dispatch.

    Translates StructuredIntent → Task payload understood by TodoAnalysisAgent:
      intent.action              → payload["query"]
      intent.entities["prompt_name"] → payload["prompt"]

    This is intentionally domain-specific — the framework's generic DirectStrategy
    doesn't know the "prompt" key convention. Each domain strategy owns that mapping.
    """

    strategy_id = DIRECT

    def applicable(self, intent: StructuredIntent, context: ExecutionContext) -> bool:
        return True

    def estimate_cost(
        self, intent: StructuredIntent, context: ExecutionContext
    ) -> CostEstimate:
        return CostEstimate(
            input_tokens_est=3_500,
            output_tokens_est=300,
            usd_est=0.0002,
            steps_est=1,
        )

    async def execute(
        self,
        intent: StructuredIntent,
        context: ExecutionContext,
        agent_pool: IAgentPool,
        verifier: IVerifier,
    ) -> CognitiveResult:
        prompt_name = intent.entities.get("prompt_name", "analyze")
        task = Task(
            task_id=f"todo-{context.correlation_id}-{intent.intent_type}",
            payload={"query": intent.action, "prompt": prompt_name},
        )

        # AgentPool.dispatch accepts optional context (passes strategy_id to agent).
        # IAgentPool Protocol only requires dispatch(task) for generic callers;
        # here we know we have a concrete AgentPool so we pass context.
        if isinstance(agent_pool, AgentPool):
            result = await agent_pool.dispatch(task, context)
        else:
            result = await agent_pool.dispatch(task)

        return CognitiveResult(
            content=str(result.output),
            confidence=0.9,
            strategy_id=self.strategy_id,
        )
