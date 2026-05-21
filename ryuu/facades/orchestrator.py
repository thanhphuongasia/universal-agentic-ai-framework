"""Orchestrator — main agent plans, workers execute per item, aggregate combines."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import anyio

from ryuu.factory import Agent


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
