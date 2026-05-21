"""Phase 10.5 — Multi-agent facades.

5 pattern classes wrapping Agent + AgentPool primitives:
  Chain         — sequential output→input (with optional callable transforms)
  FanOut        — parallel N tasks (3 variants: items / agents / pairs)
  Router        — analyzer dispatches to one of N routes
  Orchestrator  — main agent plans, workers execute per item, aggregate combines
  Evaluator     — generate → verify → refine if bad → repeat

All implement uniform `.run(input) → output` for composability.

See: docs/guides/quickstart.md §4 (multi-agent patterns).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import anyio

from ryuu.factory import Agent


# ---------------------------------------------------------------------------
# Helper — execute a step (Agent or callable) on input
# ---------------------------------------------------------------------------


async def _run_step(step: Any, input_value: Any) -> Any:
    """Execute one step on input. Step may be:
      - Agent (uses .run() then extracts .output)
      - Facade (Chain/FanOut/Router/Orchestrator/Evaluator) — uses .run() directly
      - Plain callable / async callable (transform)
    """
    if isinstance(step, Agent):
        result = await step.run(str(input_value))
        return result.output
    # Facades and any object with async .run() returning value directly
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


# ---------------------------------------------------------------------------
# Chain — sequential pipeline
# ---------------------------------------------------------------------------


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
            current = await _run_step(step, current)
        return current


# ---------------------------------------------------------------------------
# FanOut — parallel execution
# ---------------------------------------------------------------------------


@dataclass
class FanOut:
    """Parallel N-way fan-out. Pick exactly ONE of the 3 variants.

    Variant 1 — data: same agent, N items, with template formatting.
        FanOut(agent=a, items=["x", "y"], template="Process {item}")

    Variant 2 — agents: N agents, same input.
        FanOut(agents=[security_agent, perf_agent, style_agent])

    Variant 3 — pairs: explicit (agent, input) tuples for max flexibility.
        FanOut(pairs=[(agent1, "task1"), (agent2, "task2")])
    """

    agent: Agent | None = None
    items: list[Any] | None = None
    template: str = "{item}"

    agents: list[Agent] | None = None

    pairs: list[tuple[Agent, str]] | None = None

    def __post_init__(self) -> None:
        modes_set = sum([
            self.items is not None,
            self.agents is not None,
            self.pairs is not None,
        ])
        if modes_set != 1:
            raise ValueError(
                "FanOut requires exactly one of: `items=` (with `agent=`), "
                "`agents=`, or `pairs=`."
            )

    async def run(self, input_value: Any = "") -> list[Any]:
        if self.pairs is not None:
            tasks: list[tuple[Agent, str]] = [(a, inp) for a, inp in self.pairs]
        elif self.agents is not None:
            tasks = [(a, str(input_value)) for a in self.agents]
        else:
            assert self.agent is not None and self.items is not None
            tasks = [
                (self.agent, self.template.format(item=item))
                for item in self.items
            ]

        results: list[Any] = [None] * len(tasks)

        async def _runner(idx: int, agent: Agent, inp: str) -> None:
            r = await agent.run(inp)
            results[idx] = r.output

        async with anyio.create_task_group() as tg:
            for i, (agent, inp) in enumerate(tasks):
                tg.start_soon(_runner, i, agent, inp)

        return results


# ---------------------------------------------------------------------------
# Router — analyzer dispatches to one of N routes
# ---------------------------------------------------------------------------


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
        return await _run_step(target, input_value)


# ---------------------------------------------------------------------------
# Orchestrator — main plans + workers execute + aggregate combines
# ---------------------------------------------------------------------------


@dataclass
class Orchestrator:
    """Main agent generates a plan; workers spawn per planned item; aggregate combines.

    Flow:
        main_output = await main.run(input)
        items = plan_items(main_output)
        worker_outputs = [await workers(item).run(item) for item in items]
        return aggregate(worker_outputs)

    `workers` is a factory: `Callable[[item], Agent]` — different config per item.
    """

    main: Agent
    workers: Callable[[Any], Agent]
    plan_items: Callable[[str], list[Any]]
    aggregate: Callable[[list[Any]], Any]

    async def run(self, input_value: Any) -> Any:
        main_result = await self.main.run(str(input_value))
        items = self.plan_items(main_result.output)

        worker_outputs: list[Any] = [None] * len(items)

        async def _runner(idx: int, item: Any) -> None:
            worker = self.workers(item)
            r = await worker.run(str(item))
            worker_outputs[idx] = r.output

        async with anyio.create_task_group() as tg:
            for i, item in enumerate(items):
                tg.start_soon(_runner, i, item)

        return self.aggregate(worker_outputs)


# ---------------------------------------------------------------------------
# Evaluator — generate → verify → refine
# ---------------------------------------------------------------------------


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

        for attempt in range(self.max_refines + 1):
            result = await self.generator.run(current_input)
            last_output = result.output

            passed, feedback = self.verifier(last_output)
            if passed:
                return last_output

            # Refine: append feedback for next attempt
            current_input = f"{input_value}\n\nPrevious attempt feedback: {feedback}\nRetry."

        return last_output   # all refines exhausted, return last
