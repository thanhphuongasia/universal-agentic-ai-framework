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
    """Generate a draft, evaluate it, refine until it passes or max_rounds exhausted."""

    strategy_id = EVALUATOR_OPTIMIZER

    def __init__(self, max_rounds: int = 3) -> None:
        self.max_rounds = max_rounds

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
            result = await agent_pool.dispatch(task)
            output = str(result.output)

            verification = await verifier.verify(output, context)
            if verification.confidence > best_confidence:
                best_output = output
                best_confidence = verification.confidence

            if verification.passed:
                return CognitiveResult(
                    content=output,
                    confidence=verification.confidence,
                    strategy_id=EVALUATOR_OPTIMIZER,
                )

            feedback = verification.feedback

        return CognitiveResult(
            content=best_output,
            confidence=best_confidence,
            strategy_id=EVALUATOR_OPTIMIZER,
        )
