"""FanOut — parallel N-way execution (3 variants: items / agents / pairs)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import anyio

from ryuu.factory import Agent


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
