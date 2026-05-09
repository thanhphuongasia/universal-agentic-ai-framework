"""Todo-domain ICognitiveStrategy implementations — 4 strategies.

  TodoParallelStrategy   — "each goal / separately" → fan_out per goal
  TodoEvaluatorStrategy  — intent_type=="report"   → dispatch + verify JSON, refine if bad
  TodoReActStrategy      — suggests react + complexity ≥ MEDIUM
  TodoDirectStrategy     — fallback (always applicable)

Hybrid pattern: LLM hints (`intent.suggested_strategy`), code constrains
(`applicable()` checks the hint AND business rules).

All 4 bridge StructuredIntent → Task payload that TodoAnalysisAgent._execute()
understands ({"query": ..., "prompt": ...}).
"""

from __future__ import annotations

import json

from uaaf.cognitive.strategy import IAgentPool, IVerifier
from uaaf.execution.agent import Task
from uaaf.execution.pool import AgentPool
from uaaf.intent.models import (
    DIRECT,
    EVALUATOR_OPTIMIZER,
    PARALLEL_FANOUT,
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


# ---------------------------------------------------------------------------
# Evaluator-Optimizer: dispatch → verify JSON → refine if invalid
# ---------------------------------------------------------------------------

class TodoEvaluatorStrategy:
    """Generate → evaluate → refine pattern for JSON-output queries.

    applicable: intent_type == "report" — analyzer flagged this as a structured
    output query (priority breakdown, stats, etc).

    On first dispatch: parse output as JSON.
      - Valid JSON   → return (confidence=0.95, no refine)
      - Invalid JSON → re-dispatch with stricter "return ONLY valid JSON" hint
                       (confidence=0.7, even if 2nd attempt also fails)
    """

    strategy_id = EVALUATOR_OPTIMIZER

    def applicable(self, intent: StructuredIntent, context: ExecutionContext) -> bool:
        return intent.intent_type == "report"

    def estimate_cost(
        self, intent: StructuredIntent, context: ExecutionContext
    ) -> CostEstimate:
        return CostEstimate(
            input_tokens_est=7_000,
            output_tokens_est=400,
            usd_est=0.0004,
            steps_est=2,  # worst case: generate + refine
        )

    async def execute(
        self,
        intent: StructuredIntent,
        context: ExecutionContext,
        agent_pool: IAgentPool,
        verifier: IVerifier,
    ) -> CognitiveResult:
        prompt_name = intent.entities.get("prompt_name", "priority_breakdown")
        task = Task(
            task_id=f"todo-eval-{context.correlation_id}",
            payload={"query": intent.action, "prompt": prompt_name},
        )

        if isinstance(agent_pool, AgentPool):
            result = await agent_pool.dispatch(task, context)
        else:
            result = await agent_pool.dispatch(task)

        output = str(result.output)
        if _looks_like_json(output):
            return CognitiveResult(
                content=output, confidence=0.95, strategy_id=self.strategy_id
            )

        refined_task = Task(
            task_id=f"todo-eval-refine-{context.correlation_id}",
            payload={
                "query": intent.action + " — Return ONLY valid JSON, no prose.",
                "prompt": prompt_name,
            },
        )
        if isinstance(agent_pool, AgentPool):
            refined = await agent_pool.dispatch(refined_task, context)
        else:
            refined = await agent_pool.dispatch(refined_task)

        return CognitiveResult(
            content=str(refined.output),
            confidence=0.70,
            strategy_id=self.strategy_id,
        )


def _looks_like_json(text: str) -> bool:
    """Cheap JSON-shape check — handles plain JSON or fenced ```json blocks."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.split("\n")
        if len(lines) > 2:
            stripped = "\n".join(lines[1:-1])
    try:
        json.loads(stripped)
        return True
    except (json.JSONDecodeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Parallel fan-out: split per-goal queries → dispatch concurrently → aggregate
# ---------------------------------------------------------------------------

_PARALLEL_KEYWORDS = frozenset({"each goal", "every goal", "separately", "individually"})


class TodoParallelStrategy:
    """Fan out one query into N per-goal subtasks, dispatch in parallel.

    applicable: action contains "each goal" / "every goal" / "separately" /
    "individually" — heuristic that the user wants per-entity analysis.

    Splits into 1 subtask per goal (g1, g2, g3), dispatches concurrently via
    AgentPool.fan_out, joins outputs with goal labels.
    """

    strategy_id = PARALLEL_FANOUT
    GOAL_IDS = ("g1", "g2", "g3")

    def applicable(self, intent: StructuredIntent, context: ExecutionContext) -> bool:
        action = intent.action.lower()
        return any(kw in action for kw in _PARALLEL_KEYWORDS)

    def estimate_cost(
        self, intent: StructuredIntent, context: ExecutionContext
    ) -> CostEstimate:
        n = len(self.GOAL_IDS)
        return CostEstimate(
            input_tokens_est=3_500 * n,
            output_tokens_est=200 * n,
            usd_est=0.0002 * n,
            steps_est=n,
        )

    async def execute(
        self,
        intent: StructuredIntent,
        context: ExecutionContext,
        agent_pool: IAgentPool,
        verifier: IVerifier,
    ) -> CognitiveResult:
        prompt_name = intent.entities.get("prompt_name", "analyze")
        tasks = [
            Task(
                task_id=f"todo-par-{context.correlation_id}-{gid}",
                payload={
                    "query": f"{intent.action} (focus only on goal {gid})",
                    "prompt": prompt_name,
                },
            )
            for gid in self.GOAL_IDS
        ]

        if isinstance(agent_pool, AgentPool):
            results = await agent_pool.fan_out(tasks, context, on_error="collect")
        else:
            # Generic IAgentPool — sequential fallback
            results = [await agent_pool.dispatch(t) for t in tasks]

        combined = "\n\n".join(
            f"━━ {gid.upper()} ━━\n{r.output}"
            for gid, r in zip(self.GOAL_IDS, results, strict=True)
        )
        return CognitiveResult(
            content=combined,
            confidence=0.85,
            strategy_id=self.strategy_id,
        )
