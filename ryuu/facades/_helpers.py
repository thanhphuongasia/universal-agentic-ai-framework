"""Shared helpers for facade implementations."""

from __future__ import annotations

from typing import Any

from ryuu.factory import Agent


async def run_step(step: Any, input_value: Any) -> Any:
    """Execute one step on input. Step may be:
      - Agent (uses .run() then extracts .output)
      - Facade (any object with async .run() returning value directly)
      - Plain callable / async callable (transform)
    """
    if isinstance(step, Agent):
        result = await step.run(str(input_value))
        return result.output
    if hasattr(step, "run") and callable(step.run):
        out = step.run(input_value)
        if hasattr(out, "__await__"):
            out = await out
        return out
    if callable(step):
        out = step(input_value)
        if hasattr(out, "__await__"):
            out = await out
        return out
    raise TypeError(f"Unsupported step type: {type(step)}")
