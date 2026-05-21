"""AdaptiveStrategy — Phase 14.3.

Compute-adaptive effort allocation. Cheap difficulty classifier (`trivial`/
`medium`/`hard`) selects model + iteration budget per query.

Layer A (cognitive mechanism). Layer B Factory wires `adaptive_compute=True`.

Cost-saving estimate: 40-60% on chat volume where most queries are trivial/medium.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from ryuu_cognitive.strategy import IAgentPool, IVerifier
from ryuu_core.context import ExecutionContext
from ryuu_core.models import (
    CognitiveResult,
    CostEstimate,
    StructuredIntent,
    Task,
)

Difficulty = Literal["trivial", "medium", "hard"]

_DEFAULT_TIER_MODELS: dict[str, str] = {
    "trivial": "gpt-4o-mini",
    "medium":  "gpt-4o-mini",
    "hard":    "gpt-4o",
}

_DEFAULT_TIER_MAX_ITER: dict[str, int] = {"trivial": 2, "medium": 4, "hard": 8}
_DEFAULT_TIER_MAX_TOKENS: dict[str, int] = {"trivial": 300, "medium": 800, "hard": 2000}


@dataclass
class AdaptiveStrategy:
    """Difficulty-aware tier dispatch.

    `difficulty_fn` is a callable `(query: str) -> Difficulty` that returns
    "trivial" | "medium" | "hard". Default = simple keyword heuristic.

    `tier_models` / `tier_max_iterations` / `tier_max_tokens` override defaults
    per tier (consumer policy).
    """

    strategy_id: str = "adaptive"
    difficulty_fn: Callable[[str], Difficulty] | None = None
    tier_models: dict[str, str] = field(default_factory=lambda: dict(_DEFAULT_TIER_MODELS))
    tier_max_iterations: dict[str, int] = field(default_factory=lambda: dict(_DEFAULT_TIER_MAX_ITER))
    tier_max_tokens: dict[str, int] = field(default_factory=lambda: dict(_DEFAULT_TIER_MAX_TOKENS))

    def applicable(self, intent: StructuredIntent, context: ExecutionContext) -> bool:
        return True

    def estimate_cost(
        self, intent: StructuredIntent, context: ExecutionContext
    ) -> CostEstimate:
        # Average of 3 tiers (rough)
        return CostEstimate(
            input_tokens_est=600,
            output_tokens_est=500,
            usd_est=0.0001,
            steps_est=2,   # 1 classifier + 1 main call
        )

    async def execute(
        self,
        intent: StructuredIntent,
        context: ExecutionContext,
        agent_pool: IAgentPool,
        verifier: IVerifier,
    ) -> CognitiveResult:
        difficulty = self._classify(intent.action)

        task = Task(
            task_id=f"adaptive-{difficulty}-{context.correlation_id}",
            payload={
                "intent_type": intent.intent_type,
                "action": intent.action,
                "entities": intent.entities,
                "message": intent.action,
                # Tier override hints — agent_pool reads + applies
                "tier_model": self.tier_models[difficulty],
                "tier_max_iterations": self.tier_max_iterations[difficulty],
                "tier_max_tokens": self.tier_max_tokens[difficulty],
                "difficulty": difficulty,
            },
        )
        result = await agent_pool.dispatch(task)
        return CognitiveResult(
            content=str(result.output),
            confidence=0.95,
            reasoning=f"classified as {difficulty}",
            strategy_id=self.strategy_id,
        )

    def _classify(self, query: str) -> Difficulty:
        """Use difficulty_fn if provided, else keyword heuristic."""
        if self.difficulty_fn is not None:
            return self.difficulty_fn(query)
        return _heuristic_difficulty(query)


_HARD_KEYWORDS = frozenset({
    "analyze", "compare", "evaluate", "design", "architect", "trace",
    "explain why", "breakdown", "strategy", "optimize", "diagnose",
})

_TRIVIAL_KEYWORDS = frozenset({
    "what is", "define", "list", "show", "hi", "hello", "thanks",
})


def _heuristic_difficulty(query: str) -> Difficulty:
    """Cheap fallback when no explicit difficulty_fn provided.

    Reads keywords + word count. Production should pass `difficulty_fn=`
    backed by a real LLM classifier (e.g. gpt-4o-mini, 5 tokens).
    """
    q = query.lower()
    word_count = len(q.split())

    if any(kw in q for kw in _HARD_KEYWORDS) or word_count > 30:
        return "hard"
    if any(kw in q for kw in _TRIVIAL_KEYWORDS) and word_count < 8:
        return "trivial"
    return "medium"


__all__ = ["AdaptiveStrategy", "Difficulty"]
