"""Evaluator — generate → verify → refine if bad → repeat."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ryuu.factory import Agent


@dataclass
class Evaluator:
    """Generate → verify → refine if bad → repeat up to `max_refines` times.

    `verifier(output) -> (passed: bool, feedback: str)`. On failure, generator
    re-runs with feedback appended to the input prompt.

    If all refines exhausted, returns last attempt (best-effort).
    """

    generator: Agent
    verifier: Callable[[str], tuple[bool, str]]
    max_refines: int = 2

    def __post_init__(self) -> None:
        if self.max_refines < 0:
            raise ValueError(f"max_refines must be >= 0, got {self.max_refines}")

    async def run(self, input_value: Any) -> str:
        current_input = str(input_value)
        last_output = ""

        for _ in range(self.max_refines + 1):
            result = await self.generator.run(current_input)
            last_output = result.output

            passed, feedback = self.verifier(last_output)
            if passed:
                return last_output

            # Refine: append feedback for next attempt
            current_input = f"{input_value}\n\nPrevious attempt feedback: {feedback}\nRetry."

        return last_output   # all refines exhausted, return last
