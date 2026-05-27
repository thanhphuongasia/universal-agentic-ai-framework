"""ReActStrategy — ACADEMIC DEMO of the 2022 ReAct paper text protocol.

⚠️ DO NOT USE IN PRODUCTION.

For production, use `LLMAgent._react_loop()` which drives the provider's
native tool-calling API (JSON tool_use blocks). That is how Claude Code,
Cursor, Devin etc. actually implement ReAct — reliable, streaming, typed.

This class re-implements the original paper's text protocol (DONE:/ACTION:)
purely for educational purposes — to show what ReAct looked like before
function calling APIs existed.

Prompt source: packages/ryuu-cognitive/src/ryuu_cognitive/prompts/react/v1.yaml
"""

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
_ACTION_PREFIX = "ACTION:"

# System prompt suffix injected into every ReAct step task.
# Explicit format + examples → works with weak models (haiku, gpt-4o-mini).
_REACT_SYSTEM = """\
You are a step-by-step reasoning agent. Solve the given intent by \
thinking and acting one step at a time.

STRICT OUTPUT FORMAT — choose exactly one:
  DONE:<your complete answer>
  ACTION:<one specific next action to take>

RULES:
1. Output ONLY a single line starting with DONE: or ACTION:.
2. No prose, no explanation, no extra lines.
3. DONE: when you are confident the answer is complete.
4. ACTION: when you still need more information.
5. Each ACTION should be concrete and specific — not vague.

EXAMPLES:
Intent: find the capital of France | Observations: none
→ ACTION:search for the capital city of France

Intent: find the capital of France | Observations: Paris is the capital.
→ DONE:Paris

Intent: compare Python vs JS speed | Observations: Python IO 50ms, JS IO 20ms. Python CPU 200ms, JS CPU 80ms.
→ DONE:JavaScript is faster than Python for both IO (~2.5x) and CPU (~2.5x) tasks.\
"""

# Per-step user message template.
_REACT_USER = (
    "Intent: {intent_type} — {action}\n"
    "Entities: {entities}\n\n"
    "Steps taken so far:\n{observations}\n\n"
    "Your response (DONE:<answer> or ACTION:<next_action>):"
)


class ReActStrategy:
    """⚠️ ACADEMIC DEMO — text-protocol ReAct from the 2022 paper.

    Each step dispatches a task; the agent's LLM responds with DONE:<answer>
    or ACTION:<next>. Loop stops on DONE.

    For production code, use `LLMAgent._react_loop()` instead — it drives
    the provider's native tool-calling API which is reliable and streaming.
    """

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
            obs_text = "\n".join(f"- {o}" for o in observations) if observations else "none"
            message = _REACT_USER.format(
                intent_type=intent.intent_type,
                action=intent.action,
                entities=intent.entities,
                observations=obs_text,
            )
            task = Task(
                task_id=f"react-{context.correlation_id}-step{step}",
                payload={
                    "message": message,
                    "intent_type": intent.intent_type,
                    "system_prompt_suffix": _REACT_SYSTEM,
                },
            )
            result = await agent_pool.dispatch(task)
            last_output = str(result.output).strip()

            if last_output.startswith(_DONE_PREFIX):
                answer = last_output[len(_DONE_PREFIX):].strip()
                return CognitiveResult(
                    content=answer,
                    confidence=0.9,
                    reasoning="\n".join(observations),
                    strategy_id=REACT,
                )

            # Strip ACTION: prefix before storing as observation
            obs = (
                last_output[len(_ACTION_PREFIX):].strip()
                if last_output.startswith(_ACTION_PREFIX)
                else last_output
            )
            observations.append(obs)

        return CognitiveResult(
            content=last_output,
            confidence=0.5,
            reasoning="\n".join(observations),
            strategy_id=REACT,
        )
