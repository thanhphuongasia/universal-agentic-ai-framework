"""Chain — sequential pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ryuu.facades._helpers import run_step


@dataclass
class Chain:
    """Sequential pipeline: output of step N → input of step N+1.

    Steps can be Agent OR callable (for pure transforms between agents).
    """

    steps: list[Any]

    def __post_init__(self) -> None:
        if not self.steps:
            raise ValueError("Chain cannot be empty")

    async def run(self, input_value: Any) -> Any:
        current = input_value
        for step in self.steps:
            current = await run_step(step, current)
        return current
