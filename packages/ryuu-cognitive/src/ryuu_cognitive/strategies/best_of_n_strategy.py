"""BestOfNStrategy — Phase 14.2.

Sample N candidates concurrently + aggregate via vote mode. Reduces flapping
on ambiguous/non-deterministic outputs.

Layer A (cognitive mechanism). Layer B Factory wires `n_samples=N, vote=...`.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from ryuu_cognitive.strategy import IAgentPool, IVerifier
from ryuu_core.context import ExecutionContext
from ryuu_core.models import (
    CognitiveResult,
    CostEstimate,
    StructuredIntent,
    Task,
)

VoteMode = Literal["majority", "llm_judge", "score_fn"]


@dataclass
class BestOfNStrategy:
    """Sample N candidates concurrently + aggregate via vote.

    Modes:
      - majority: Counter(samples).most_common(1) — for categorical outputs
      - llm_judge: verifier scores each sample, pick max — for quality grading
      - score_fn:  user-supplied Callable[[str], float] — for custom heuristics
    """

    strategy_id: str = "best_of_n"
    n: int = 3
    vote: VoteMode = "majority"
    confidence_threshold: float | None = None   # skip best-of-N if primary > threshold (reserved)
    verifier: Any | None = None                  # for vote="llm_judge" — agent or callable
    score_fn: Callable[[str], float] | None = None   # for vote="score_fn"

    def applicable(self, intent: StructuredIntent, context: ExecutionContext) -> bool:
        return True

    def estimate_cost(
        self, intent: StructuredIntent, context: ExecutionContext
    ) -> CostEstimate:
        # N× single-call cost
        return CostEstimate(
            input_tokens_est=500 * self.n,
            output_tokens_est=200 * self.n,
            usd_est=0.0001 * self.n,
            steps_est=self.n,
        )

    async def execute(
        self,
        intent: StructuredIntent,
        context: ExecutionContext,
        agent_pool: IAgentPool,
        verifier: IVerifier,
    ) -> CognitiveResult:
        # Build N parallel tasks
        tasks = [
            Task(
                task_id=f"best-of-n-{context.correlation_id}-{i}",
                payload={
                    "intent_type": intent.intent_type,
                    "action": intent.action,
                    "entities": intent.entities,
                    "message": intent.action,
                },
            )
            for i in range(self.n)
        ]

        # Parallel dispatch via gather (works with any IAgentPool)
        results = await asyncio.gather(
            *(agent_pool.dispatch(t) for t in tasks)
        )
        samples = [str(r.output) for r in results]

        winner, confidence = _aggregate(
            samples, mode=self.vote,
            score_fn=self.score_fn, verifier=self.verifier,
        )
        return CognitiveResult(
            content=winner,
            confidence=confidence,
            strategy_id=self.strategy_id,
            evidence=samples,
        )


def _aggregate(
    samples: list[str],
    *,
    mode: VoteMode,
    score_fn: Callable[[str], float] | None,
    verifier: Any | None,
) -> tuple[str, float]:
    """Return (winner, confidence)."""
    if not samples:
        return "", 0.0

    if mode == "majority":
        counts = Counter(samples)
        winner, count = counts.most_common(1)[0]
        return winner, count / len(samples)

    if mode == "score_fn":
        if score_fn is None:
            raise ValueError("vote='score_fn' requires score_fn callable")
        scored = sorted(samples, key=score_fn, reverse=True)
        return scored[0], score_fn(scored[0])

    if mode == "llm_judge":
        if verifier is None:
            raise ValueError("vote='llm_judge' requires verifier")
        # Simple: caller-provided callable returning float per sample
        # (verifier integration deferred — for now treat as score_fn-like)
        if callable(verifier):
            scored = sorted(samples, key=verifier, reverse=True)
            return scored[0], float(verifier(scored[0]))
        raise ValueError("verifier must be callable returning float")

    raise ValueError(f"Unknown vote mode: {mode!r}")
