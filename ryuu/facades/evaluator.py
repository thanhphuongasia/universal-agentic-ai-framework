"""Evaluator — generate → verify → refine if bad → repeat."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ryuu.factory import Agent
from ryuu.refine_logger import RefineEvent, RefineLogger


@dataclass
class Evaluator:
    """Generate → verify → refine if bad → repeat up to `max_refines` times.

    `verifier(output) -> (passed: bool, feedback: str)`. On failure, generator
    re-runs with feedback appended to the input prompt.

    If all refines exhausted, returns last attempt (best-effort).

    Optional `refine_logger=RefineLogger(...)` captures each refine cycle to
    JSONL — feeds back into `ryuu.PromptOptimizer` for continuous prompt
    improvement based on production failures.
    """

    generator: Agent
    verifier: Callable[[str], tuple[bool, str]]
    max_refines: int = 2
    refine_logger: RefineLogger | None = None
    extra_metadata: dict[str, Any] = field(default_factory=dict)
    """Project-specific context attached to each logged RefineEvent.extra"""

    def __post_init__(self) -> None:
        if self.max_refines < 0:
            raise ValueError(f"max_refines must be >= 0, got {self.max_refines}")

    async def run(self, input_value: Any) -> str:
        initial_prompt = str(input_value)
        current_input = initial_prompt
        last_output = ""
        feedback_history: list[str] = []
        passed_final = False

        for iteration in range(self.max_refines + 1):
            result = await self.generator.run(current_input)
            last_output = result.output

            passed, feedback = self.verifier(last_output)
            if passed:
                passed_final = True
                self._log_if_refined(
                    initial_prompt, last_output, feedback_history, iteration, True,
                )
                return last_output

            feedback_history.append(feedback)
            # Refine: append feedback for next attempt
            current_input = (
                f"{initial_prompt}\n\nPrevious attempt feedback: {feedback}\nRetry."
            )

        # All refines exhausted
        self._log_if_refined(
            initial_prompt, last_output, feedback_history,
            self.max_refines + 1, passed_final,
        )
        return last_output

    def _log_if_refined(
        self,
        initial_prompt: str,
        final_output: str,
        feedback_history: list[str],
        refine_count: int,
        passed: bool,
    ) -> None:
        """Append RefineEvent to logger if attached và refine_count > 0."""
        if self.refine_logger is None or refine_count == 0:
            return
        event = RefineEvent(
            initial_prompt=initial_prompt,
            feedback_history=list(feedback_history),
            final_output=final_output,
            refine_count=refine_count,
            passed=passed,
            extra=dict(self.extra_metadata),
        )
        self.refine_logger.log(event)
