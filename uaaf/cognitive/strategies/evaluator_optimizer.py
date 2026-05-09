"""EvaluatorOptimizerStrategy — generate→verify→refine loop — P1-T06."""

from __future__ import annotations

from uaaf.cognitive.strategy import IAgentPool, IVerifier
from uaaf.execution.agent import Task
from uaaf.intent.models import (
    EVALUATOR_OPTIMIZER,
    CognitiveResult,
    ComplexityLevel,
    CostEstimate,
    StructuredIntent,
)
from uaaf.runtime.context import ExecutionContext


class EvaluatorOptimizerStrategy:
    """Generate a draft, evaluate it, refine until it passes or max_rounds exhausted.

    When `verbose=True`, prints `[generator]` / `[evaluator]` markers so callers
    can see which side of the loop is acting at each step. Off by default — keep
    framework code silent in production; turn on for demos / debugging.
    """

    strategy_id = EVALUATOR_OPTIMIZER

    def __init__(self, max_rounds: int = 3, verbose: bool = False) -> None:
        self.max_rounds = max_rounds
        self.verbose = verbose

    def applicable(self, intent: StructuredIntent, context: ExecutionContext) -> bool:
        return intent.complexity == ComplexityLevel.HIGH

    def estimate_cost(self, intent: StructuredIntent, context: ExecutionContext) -> CostEstimate:
        return CostEstimate(
            input_tokens_est=1500,
            output_tokens_est=600,
            usd_est=0.005,
            steps_est=self.max_rounds * 2,
        )

    async def execute(
        self,
        intent: StructuredIntent,
        context: ExecutionContext,
        agent_pool: IAgentPool,
        verifier: IVerifier,
    ) -> CognitiveResult:
        feedback = ""
        best_output = ""
        best_confidence = 0.0

        for round_num in range(self.max_rounds):
            prompt = (
                f"Intent: {intent.intent_type} — {intent.action}\n"
                f"Entities: {intent.entities}\n"
            )
            if feedback:
                prompt += f"\nPrevious feedback to address:\n{feedback}\n"
            prompt += "\nGenerate a high-quality response."

            task = Task(
                task_id=f"eo-{context.correlation_id}-round{round_num}",
                payload={"message": prompt, "intent_type": intent.intent_type},
            )

            if self.verbose:
                tag = "generator (refine)" if feedback else "generator"
                print(f"  ⚙️  [{tag}] round {round_num + 1}/{self.max_rounds}: dispatching…")

            result = await agent_pool.dispatch(task)
            output = str(result.output)

            if self.verbose:
                print(f"  🔍 [evaluator] verifying round {round_num + 1} output…")

            verification = await verifier.verify(output, context)
            if verification.confidence > best_confidence:
                best_output = output
                best_confidence = verification.confidence

            if verification.passed:
                if self.verbose:
                    print(
                        f"  ✅ [evaluator] passed (confidence={verification.confidence:.2f}) "
                        f"— returning round {round_num + 1} output"
                    )
                return CognitiveResult(
                    content=output,
                    confidence=verification.confidence,
                    strategy_id=EVALUATOR_OPTIMIZER,
                )

            feedback = verification.feedback
            if self.verbose:
                snippet = feedback[:80] + ("…" if len(feedback) > 80 else "")
                print(
                    f"  ↻  [evaluator] failed (confidence={verification.confidence:.2f}) "
                    f"→ feeding back to generator: {snippet!r}"
                )

        if self.verbose:
            print(
                f"  ⏹  [evaluator] max_rounds={self.max_rounds} exhausted — "
                f"returning best (confidence={best_confidence:.2f})"
            )
        return CognitiveResult(
            content=best_output,
            confidence=best_confidence,
            strategy_id=EVALUATOR_OPTIMIZER,
        )
