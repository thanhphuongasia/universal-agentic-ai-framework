"""Todo-domain ICognitiveStrategy implementations.

  TodoReActStrategy   — applicable when LLM suggests react + complexity ≥ MEDIUM
  TodoDirectStrategy  — fallback (always applicable)

Hybrid pattern: LLM hints (`intent.suggested_strategy`), code constrains
(`applicable()` checks both the hint AND business rules like complexity tier).

Both bridge StructuredIntent → Task payload that TodoAnalysisAgent._execute()
understands ({"query": ..., "prompt": ...}).
"""

from __future__ import annotations

from uaaf.cognitive.strategy import IAgentPool, IVerifier
from uaaf.execution.agent import Task
from uaaf.execution.pool import AgentPool
from uaaf.intent.models import (
    DIRECT,
    REACT,
    CognitiveResult,
    ComplexityLevel,
    CostEstimate,
    StructuredIntent,
)
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


# ---------------------------------------------------------------------------
# Hybrid: ReAct strategy — picked only if LLM suggests + complexity is MEDIUM+
# ---------------------------------------------------------------------------

class TodoReActStrategy:
    """Multi-step strategy gated by hybrid rule (LLM hint + business policy).

    applicable() returns True ONLY when:
      • intent.suggested_strategy == REACT  (LLM thinks react fits)  AND
      • intent.complexity >= MEDIUM         (we don't pay react cost on trivial queries)

    The agent itself already does Thought→Action→Observation via _react_loop()
    for tool calling — this strategy simply acknowledges multi-step intent at
    the cognitive layer, stamps strategy_id="react", and could later be extended
    to dispatch multiple times (planning → refinement) if needed.
    """

    strategy_id = REACT

    def applicable(self, intent: StructuredIntent, context: ExecutionContext) -> bool:
        return (
            intent.suggested_strategy == REACT
            and intent.complexity >= ComplexityLevel.MEDIUM
        )

    def estimate_cost(
        self, intent: StructuredIntent, context: ExecutionContext
    ) -> CostEstimate:
        return CostEstimate(
            input_tokens_est=4_500,
            output_tokens_est=600,
            usd_est=0.0005,
            steps_est=3,   # conceptual — actual loop happens inside agent
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
            task_id=f"todo-react-{context.correlation_id}-{intent.intent_type}",
            payload={"query": intent.action, "prompt": prompt_name},
        )

        if isinstance(agent_pool, AgentPool):
            result = await agent_pool.dispatch(task, context)
        else:
            result = await agent_pool.dispatch(task)

        return CognitiveResult(
            content=str(result.output),
            confidence=0.9,
            strategy_id=self.strategy_id,
        )
