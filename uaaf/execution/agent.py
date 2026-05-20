"""BaseAgent — template method class that injects cross-cutting into every agent.

IMPORTANT: Subclasses implement ``_execute()`` only.
           Do NOT override ``execute()`` — cross-cutting cannot be opted out.

The template method pattern enforces:
  trace → rate-limit → budget-check → audit-start → execute → cost-record → audit-complete

Any exception from ``_execute()`` is classified and re-raised:
  - RetryableError / DegradedError → re-raise as-is (caller decides)
  - Any other Exception            → wrapped in FatalError + audit-logged
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from uaaf.observability.audit import AuditLogger
from uaaf.observability.cost import Cost, CostTracker
from uaaf_workflow.errors import DegradedError, FatalError, RetryableError
from uaaf.observability.rate_limit import RateLimiter
from uaaf.observability.tracer import Tracer
from uaaf_workflow.context import ExecutionContext

# ---------------------------------------------------------------------------
# Task and AgentResult value objects
# ---------------------------------------------------------------------------


@dataclass
class Task:
    """Unit of work dispatched to an agent."""

    task_id: str
    payload: dict[str, Any]
    estimated_cost: Cost | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    """Return value from a completed agent execution."""

    task_id: str
    output: Any
    cost: Cost
    success: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# BaseAgent
# ---------------------------------------------------------------------------


@dataclass
class BaseAgent(ABC):
    """Abstract base for all UAAF agents.

    Cross-cutting (cost / trace / audit / rate-limit) is wired in ``execute()``
    and cannot be bypassed.  Subclasses implement ``_execute()`` only.

    Use as a @dataclass — subclasses inherit all fields automatically::

        @dataclass
        class MyAgent(BaseAgent):
            my_field: str = "default"

            async def _execute(self, task, context):
                ...
    """

    agent_id: str
    cost_tracker: CostTracker
    tracer: Tracer
    audit_logger: AuditLogger
    rate_limiter: RateLimiter
    enforce_cognitive_routing: bool = False

    @abstractmethod
    async def _execute(self, task: Task, context: ExecutionContext) -> AgentResult:
        """Domain logic goes here.  Framework handles everything else."""

    async def execute(self, task: Task, context: ExecutionContext) -> AgentResult:
        """Template method — DO NOT OVERRIDE.

        Executes the full cross-cutting pipeline around ``_execute()``.
        """
        if self.enforce_cognitive_routing and context.strategy_id is None:
            raise RuntimeError(
                f"Agent {self.agent_id!r} called without cognitive routing "
                "(context.strategy_id is None). "
                "Use RequestHandler.handle() or set enforce_cognitive_routing=False "
                "for direct-call patterns (tests, examples)."
            )
        scope_key = context.scope.scope_key
        corr_id = context.correlation_id

        async with self.tracer.span(self.agent_id, task.task_id, corr_id):
            # 1. Rate limit (blocks until token available)
            await self.rate_limiter.acquire(scope_key, self.agent_id)

            # 2. Budget check (raises DegradedError if over budget)
            if task.estimated_cost is not None:
                self.cost_tracker.enforce(scope_key, task.estimated_cost)

            # 3. Audit start
            self.audit_logger.log_start(
                task_id=task.task_id,
                agent_id=self.agent_id,
                scope_key=scope_key,
                correlation_id=corr_id,
                payload={"payload_keys": list(task.payload.keys())},
            )

            try:
                result = await self._execute(task, context)

                # 4. Record actual cost
                self.cost_tracker.record(scope_key, result.cost)

                # 5. Audit complete
                self.audit_logger.log_complete(
                    task_id=task.task_id,
                    agent_id=self.agent_id,
                    scope_key=scope_key,
                    correlation_id=corr_id,
                    payload={"cost_usd": result.cost.usd, "success": result.success},
                )
                return result

            except (RetryableError, DegradedError):
                # Caller decides retry / fallback; just audit and re-raise.
                self.audit_logger.log_error(
                    task_id=task.task_id,
                    agent_id=self.agent_id,
                    scope_key=scope_key,
                    correlation_id=corr_id,
                    exc=Exception("retryable/degraded — see cause"),
                )
                raise

            except Exception as exc:
                # Unexpected — wrap as FatalError so callers know to escalate.
                self.audit_logger.log_error(
                    task_id=task.task_id,
                    agent_id=self.agent_id,
                    scope_key=scope_key,
                    correlation_id=corr_id,
                    exc=exc,
                )
                raise FatalError(f"Agent {self.agent_id!r} encountered unexpected error") from exc
