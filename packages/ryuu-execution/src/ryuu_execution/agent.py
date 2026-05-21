"""BaseAgent — template method class that injects cross-cutting into every agent."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ryuu_core.context import ExecutionContext
from ryuu_core.errors import DegradedError, FatalError, RetryableError
from ryuu_core.models import AgentResult as AgentResult, Task as Task  # noqa: F401 — re-export
from ryuu_core.nulls import NullAuditLogger, NullCostTracker, NullRateLimiter, NullTracer
from ryuu_core.protocols import IAuditLogger, ICostTracker, IRateLimiter, ITracer


@dataclass
class BaseAgent(ABC):
    """Abstract agent — subclasses implement ``_execute()`` only.

    The template method pattern enforces:
      trace → rate-limit → budget-check → audit-start → execute → cost-record → audit-complete

    Any exception from ``_execute()`` is classified and re-raised:
      - RetryableError / DegradedError → re-raise as-is (caller decides)
      - Any other Exception            → wrapped in FatalError + audit-logged
    """

    agent_id: str
    cost_tracker: ICostTracker = field(default_factory=NullCostTracker)
    tracer: ITracer = field(default_factory=NullTracer)
    audit_logger: IAuditLogger = field(default_factory=NullAuditLogger)
    rate_limiter: IRateLimiter = field(default_factory=NullRateLimiter)
    enforce_cognitive_routing: bool = False

    @abstractmethod
    async def _execute(self, task: Task, context: ExecutionContext) -> AgentResult: ...

    async def execute(self, task: Task, context: ExecutionContext) -> AgentResult:
        """Template method — DO NOT OVERRIDE."""
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
            await self.rate_limiter.acquire(scope_key, self.agent_id)

            if task.estimated_cost is not None:
                self.cost_tracker.enforce(scope_key, task.estimated_cost)

            self.audit_logger.log_start(
                task_id=task.task_id,
                agent_id=self.agent_id,
                scope_key=scope_key,
                correlation_id=corr_id,
                payload={"payload_keys": list(task.payload.keys())},
            )

            try:
                result = await self._execute(task, context)

                self.cost_tracker.record(scope_key, result.cost)

                self.audit_logger.log_complete(
                    task_id=task.task_id,
                    agent_id=self.agent_id,
                    scope_key=scope_key,
                    correlation_id=corr_id,
                    payload={"cost_usd": result.cost.usd, "success": result.success},
                )
                return result

            except (RetryableError, DegradedError):
                self.audit_logger.log_error(
                    task_id=task.task_id,
                    agent_id=self.agent_id,
                    scope_key=scope_key,
                    correlation_id=corr_id,
                    exc=Exception("retryable/degraded — see cause"),
                )
                raise

            except Exception as exc:
                self.audit_logger.log_error(
                    task_id=task.task_id,
                    agent_id=self.agent_id,
                    scope_key=scope_key,
                    correlation_id=corr_id,
                    exc=exc,
                )
                raise FatalError(f"Agent {self.agent_id!r} encountered unexpected error") from exc
