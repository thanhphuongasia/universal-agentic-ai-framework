"""Router — 1-stage analyzer dispatches to one of N routes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ryuu.facades._helpers import run_step


@dataclass
class Router:
    """Analyzer decides which route handles the input.

    `analyzer(input) -> route_key`. If key not in routes, falls back to
    "_default" if present, else raises KeyError.
    """

    routes: dict[str, Any]   # Any = Agent or facade with .run()
    analyzer: Callable[[Any], str | Awaitable[str]]

    def __post_init__(self) -> None:
        if not self.routes:
            raise ValueError("Router requires non-empty `routes` dict")

    async def run(self, input_value: Any) -> Any:
        key = self.analyzer(input_value)
        if hasattr(key, "__await__"):
            key = await key   # type: ignore[misc]
        target = self.routes.get(key) or self.routes.get("_default")
        if target is None:
            raise KeyError(
                f"Router: analyzer returned {key!r}, no matching route and no `_default`."
            )
        return await run_step(target, input_value)
