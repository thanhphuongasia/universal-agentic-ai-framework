"""AgentPool — concrete IAgentPool with routing strategies and fan_out.

Design:
- dispatch() uses round_robin (default) or random routing — not "first registered",
  which would silently always hit the same agent under load.
- fan_out() dispatches N tasks in parallel via anyio task group, bounded by Semaphore.
  on_error="fail_fast" (default): 1 failure cancels others and raises.
  on_error="collect": all tasks run to completion; failures stored as AgentResult(success=False).
- Results are index-stable: results[i] corresponds to tasks[i], regardless of completion order.
"""

from __future__ import annotations

import random as _random
from dataclasses import dataclass, field
from typing import Literal

import anyio

from uaaf.execution.agent import AgentResult, BaseAgent, Task
from uaaf.observability.cost import Cost
from uaaf_workflow.context import ContextScope, ExecutionContext


@dataclass
class AgentPool:
    """Registry + router + concurrent dispatcher for BaseAgent instances.

    Usage::

        pool = AgentPool(max_concurrency=4)
        pool.register(agent_a, tags={"nlp"})
        pool.register(agent_b, tags={"nlp", "fast"})

        result  = await pool.dispatch(task, context)
        results = await pool.fan_out(tasks, context, tag_filter="nlp")
    """

    max_concurrency: int = 8
    _agents: dict[str, BaseAgent] = field(default_factory=dict, init=False, repr=False)
    _tags: dict[str, set[str]] = field(default_factory=dict, init=False, repr=False)
    _rr_index: int = field(default=0, init=False, repr=False)

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------

    def register(self, agent: BaseAgent, tags: set[str] | None = None) -> None:
        """Add an agent to the pool.  Re-registering with same id overwrites."""
        self._agents[agent.agent_id] = agent
        self._tags[agent.agent_id] = set(tags or [])

    def agents_with_tag(self, tag: str) -> list[BaseAgent]:
        return [self._agents[aid] for aid, tags in self._tags.items() if tag in tags]

    def agent_ids(self) -> list[str]:
        return list(self._agents.keys())

    # ------------------------------------------------------------------
    # Internal routing
    # ------------------------------------------------------------------

    def _candidates(self, tag_filter: str | None) -> list[BaseAgent]:
        if tag_filter is None:
            return list(self._agents.values())
        return self.agents_with_tag(tag_filter)

    def _pick(
        self,
        strategy: Literal["round_robin", "random"],
        tag_filter: str | None = None,
    ) -> BaseAgent:
        candidates = self._candidates(tag_filter)
        if not candidates:
            tag_msg = f" with tag {tag_filter!r}" if tag_filter else ""
            raise ValueError(f"AgentPool has no agents{tag_msg} registered")
        if strategy == "round_robin":
            agent = candidates[self._rr_index % len(candidates)]
            self._rr_index += 1
            return agent
        return _random.choice(candidates)

    # ------------------------------------------------------------------
    # Public API — single dispatch
    # ------------------------------------------------------------------

    async def dispatch(
        self,
        task: Task,
        context: ExecutionContext | None = None,
        strategy: Literal["round_robin", "random"] = "round_robin",
    ) -> AgentResult:
        """Route one task using strategy. Raises ValueError if pool is empty."""
        agent = self._pick(strategy)
        ctx = context if context is not None else _fallback_context()
        return await agent.execute(task, ctx)

    async def dispatch_to(
        self,
        agent_id: str,
        task: Task,
        context: ExecutionContext,
    ) -> AgentResult:
        """Route to a specific agent by id. Raises KeyError if not registered."""
        if agent_id not in self._agents:
            raise KeyError(f"Agent {agent_id!r} not registered in pool")
        return await self._agents[agent_id].execute(task, context)

    # ------------------------------------------------------------------
    # Public API — parallel fan_out
    # ------------------------------------------------------------------

    async def fan_out(
        self,
        tasks: list[Task],
        context: ExecutionContext,
        tag_filter: str | None = None,
        on_error: Literal["fail_fast", "collect"] = "fail_fast",
    ) -> list[AgentResult]:
        """Dispatch N tasks in parallel; results are ordered by input task order.

        on_error="fail_fast" (default):
            anyio semantics — first failure cancels all others; ExceptionGroup raised.
        on_error="collect":
            Every task runs to completion; exceptions are stored as
            AgentResult(success=False, metadata={"error": str(exc)}).
        """
        if not tasks:
            return []

        candidates = self._candidates(tag_filter)
        if not candidates:
            tag_msg = f" with tag {tag_filter!r}" if tag_filter else ""
            raise ValueError(f"AgentPool has no agents{tag_msg} registered")

        # Index-stable pre-allocated results
        results: list[AgentResult | None] = [None] * len(tasks)
        semaphore = anyio.Semaphore(self.max_concurrency)

        if on_error == "fail_fast":
            async with anyio.create_task_group() as tg:
                for i, task in enumerate(tasks):
                    agent = candidates[i % len(candidates)]
                    tg.start_soon(_run_one, agent, task, context, results, i, semaphore)
        else:
            async with anyio.create_task_group() as tg:
                for i, task in enumerate(tasks):
                    agent = candidates[i % len(candidates)]
                    tg.start_soon(_run_collect, agent, task, context, results, i, semaphore)

        return [r for r in results if r is not None]


# ------------------------------------------------------------------
# Internal coroutines (module-level to keep AgentPool lean)
# ------------------------------------------------------------------


async def _run_one(
    agent: BaseAgent,
    task: Task,
    context: ExecutionContext,
    results: list[AgentResult | None],
    index: int,
    semaphore: anyio.Semaphore,
) -> None:
    async with semaphore:
        results[index] = await agent.execute(task, context)


async def _run_collect(
    agent: BaseAgent,
    task: Task,
    context: ExecutionContext,
    results: list[AgentResult | None],
    index: int,
    semaphore: anyio.Semaphore,
) -> None:
    async with semaphore:
        try:
            results[index] = await agent.execute(task, context)
        except Exception as exc:  # noqa: BLE001
            results[index] = AgentResult(
                task_id=task.task_id,
                output=None,
                cost=Cost.zero(),
                success=False,
                metadata={"error": str(exc)},
            )


def _fallback_context() -> ExecutionContext:
    return ExecutionContext(
        scope=ContextScope(user_id="pool", session_id="dispatch", domain="pool"),
        correlation_id="pool-dispatch",
    )
