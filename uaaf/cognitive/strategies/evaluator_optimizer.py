"""EvaluatorOptimizerStrategy — generate→verify→refine loop — P1-T06."""

from __future__ import annotations

import logging

from uaaf.cognitive.strategy import IAgentPool, IVerifier
from uaaf.execution.agent import Task
from uaaf.intent.models import (
    EVALUATOR_OPTIMIZER,
    CognitiveResult,
    ComplexityLevel,
    CostEstimate,
    StructuredIntent,
)
from uaaf_workflow.context import ExecutionContext


class EvaluatorOptimizerStrategy:
    """Generate a draft, evaluate it, refine until it passes or max_rounds exhausted.

    Emits structured INFO logs at each step under the logger name
    ``uaaf.cognitive.strategies.evaluator_optimizer`` (or a custom logger
    passed via constructor). App decides destination/format/level — framework
    stays silent unless caller configures the logger.

    Log message format (each on a single line):
        [generator] round N/M dispatching refining=<bool>
        [evaluator] verify round N
        [evaluator] passed round N confidence=0.85
        [evaluator] failed round N confidence=0.40 feedback=<text>
        [evaluator] exhausted best=0.40
    """

    strategy_id = EVALUATOR_OPTIMIZER

    def __init__(
        self,
        max_rounds: int = 3,
        logger: logging.Logger | None = None,
    ) -> None:
        self.max_rounds = max_rounds
        self._log = logger or logging.getLogger(__name__)

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

            self._log.info(
                "[generator] round %d/%d dispatching refining=%s",
                round_num + 1, self.max_rounds, bool(feedback),
            )

            result = await agent_pool.dispatch(task)
            output = str(result.output)

            self._log.info("[evaluator] verify round %d", round_num + 1)
            verification = await verifier.verify(output, context)
            if verification.confidence > best_confidence:
                best_output = output
                best_confidence = verification.confidence

            if verification.passed:
                self._log.info(
                    "[evaluator] passed round %d confidence=%.2f",
                    round_num + 1, verification.confidence,
                )
                return CognitiveResult(
                    content=output,
                    confidence=verification.confidence,
                    strategy_id=EVALUATOR_OPTIMIZER,
                )

            feedback = verification.feedback
            self._log.info(
                "[evaluator] failed round %d confidence=%.2f feedback=%s",
                round_num + 1, verification.confidence, feedback[:80],
            )

        self._log.info(
            "[evaluator] exhausted max_rounds=%d best=%.2f",
            self.max_rounds, best_confidence,
        )
        return CognitiveResult(
            content=best_output,
            confidence=best_confidence,
            strategy_id=EVALUATOR_OPTIMIZER,
        )
