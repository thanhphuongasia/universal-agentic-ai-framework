"""ThinkingStrategy — Phase 14.1.

Wraps any base agent dispatch with `<thinking>`/`<answer>` structured output.
Parses output → CognitiveResult.content (answer) + CognitiveResult.reasoning (thinking).

Layer A (cognitive mechanism). Usable from both class-based BaseAgent AND
Factory `Agent(thinking_mode=True)` (Layer B wires kwarg → this strategy).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ryuu_cognitive.strategy import IAgentPool, IVerifier
from ryuu_core.context import ExecutionContext
from ryuu_core.models import CognitiveResult, CostEstimate, StructuredIntent, Task


_THINKING_RE = re.compile(r"<thinking>(.*?)</thinking>", re.DOTALL)
_ANSWER_RE = re.compile(r"<answer>(.*?)</answer>", re.DOTALL)


_THINKING_SYSTEM_SUFFIX = (
    "\n\nProduce your response in two parts:\n"
    "<thinking>\n"
    "Step through the question carefully. Decompose. Consider options. "
    "Identify the most likely failure mode of a quick answer.\n"
    "</thinking>\n"
    "<answer>\n"
    "The actual answer, concise and direct.\n"
    "</answer>\n"
    "Always emit BOTH tags."
)


def _parse(raw: str) -> tuple[str, str]:
    thinking_m = _THINKING_RE.search(raw)
    answer_m = _ANSWER_RE.search(raw)
    answer = answer_m.group(1).strip() if answer_m else raw.strip()
    thinking = thinking_m.group(1).strip() if thinking_m else ""
    return answer, thinking


@dataclass
class ThinkingStrategy:
    """Wraps a single agent dispatch with structured <thinking>/<answer> output.

    The agent dispatch sees an augmented system prompt (instructing it to emit
    both tags). The output is parsed → CognitiveResult exposes:
      - `content`     → text inside `<answer>...</answer>`
      - `reasoning`   → text inside `<thinking>...</thinking>`

    Fallback: if either tag missing, content = raw output, reasoning = "".
    Universal — applicable() returns True for any intent.
    """

    strategy_id: str = "thinking"

    def applicable(self, intent: StructuredIntent, context: ExecutionContext) -> bool:
        return True

    def estimate_cost(
        self, intent: StructuredIntent, context: ExecutionContext
    ) -> CostEstimate:
        # Thinking adds ~200-300 output tokens for reasoning block.
        return CostEstimate(
            input_tokens_est=600,
            output_tokens_est=400,
            usd_est=0.00015,
            steps_est=1,
        )

    async def execute(
        self,
        intent: StructuredIntent,
        context: ExecutionContext,
        agent_pool: IAgentPool,
        verifier: IVerifier,
    ) -> CognitiveResult:
        # Inject thinking template via Task payload — downstream agent reads
        # `system_prompt_suffix` and concatenates to its own system prompt.
        task = Task(
            task_id=f"thinking-{context.correlation_id}",
            payload={
                "intent_type": intent.intent_type,
                "action": intent.action,
                "entities": intent.entities,
                "message": intent.action,
                "system_prompt_suffix": _THINKING_SYSTEM_SUFFIX,
                "thinking_mode": True,
            },
        )
        result = await agent_pool.dispatch(task)
        answer, thinking = _parse(str(result.output))
        return CognitiveResult(
            content=answer,
            confidence=0.9,
            reasoning=thinking,
            strategy_id=self.strategy_id,
        )
