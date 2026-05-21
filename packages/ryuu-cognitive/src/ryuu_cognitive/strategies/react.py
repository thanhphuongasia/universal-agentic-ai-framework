"""ReActStrategy — think→act→observe loop."""

from __future__ import annotations

from ryuu_cognitive.strategy import IAgentPool, IVerifier
from ryuu_core.context import ExecutionContext
from ryuu_core.models import (
    REACT,
    CognitiveResult,
    ComplexityLevel,
    CostEstimate,
    StructuredIntent,
    Task,
)

_DONE_PREFIX = "DONE:"


class ReActStrategy:
    """ReAct loop: each step dispatches a think/act task; stops on DONE signal."""

    strategy_id = REACT

    def __init__(self, max_steps: int = 6) -> None:
        self.max_steps = max_steps

    def applicable(self, intent: StructuredIntent, context: ExecutionContext) -> bool:
        return intent.complexity >= ComplexityLevel.MEDIUM

    def estimate_cost(self, intent: StructuredIntent, context: ExecutionContext) -> CostEstimate:
        return CostEstimate(
            input_tokens_est=800,
            output_tokens_est=400,
            usd_est=0.001,
            steps_est=self.max_steps,
        )

    async def execute(
        self,
        intent: StructuredIntent,
        context: ExecutionContext,
        agent_pool: IAgentPool,
        verifier: IVerifier,
    ) -> CognitiveResult:
        observations: list[str] = []
        last_output = ""

        for step in range(self.max_steps):
            obs_text = "\n".join(observations) if observations else "none"
            prompt = (
                f"Intent: {intent.intent_type} — {intent.action}\n"
                f"Entities: {intent.entities}\n"
                f"Observations so far:\n{obs_text}\n\n"
                f"Think step by step. "
                f"If you have enough information, respond with DONE:<answer>. "
                f"Otherwise respond with ACTION:<next_action>."
            )
            task = Task(
                task_id=f"react-{context.correlation_id}-step{step}",
                payload={"message": prompt, "intent_type": intent.intent_type},
            )
            result = await agent_pool.dispatch(task)
            last_output = str(result.output)

            if last_output.startswith(_DONE_PREFIX):
                answer = last_output[len(_DONE_PREFIX):]
                return CognitiveResult(
                    content=answer,
                    confidence=0.9,
                    reasoning="\n".join(observations),
                    strategy_id=REACT,
                )

            observations.append(last_output)

        return CognitiveResult(
            content=last_output,
            confidence=0.5,
            reasoning="\n".join(observations),
            strategy_id=REACT,
        )
