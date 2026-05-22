"""Phase 9 — Hook System for dynamic lifecycle injection.

Pattern inspired by Claude Agent SDK. Hooks let product code inject behavior
at agent lifecycle points without subclassing BaseAgent. Use cases: PII scrub,
approval workflow, custom metric emission, request modification.

Phase 9.1 MVP (6 events):
  PRE_EXECUTE / POST_EXECUTE / PRE_LLM / POST_LLM / ON_ERROR / ON_COMPLETE

Phase 9.2 extends with 4 more events + parallel mode:
  PRE_TOOL / POST_TOOL — around each tool invocation (PII scrub, approval gate)
  ON_BUDGET_EXCEEDED  — when BudgetExceededError raised
  ON_RATE_LIMITED     — when RateLimitTimeout raised
  Parallel fire mode  — fire-and-forget for metrics/logging (won't block path)

Deferred to Phase 9.3:
  - Decorator / class-based registration styles
  - PRE_HOOK_EVENT meta-hook (hook observing other hooks)

See: docs/guides/hooks.md, docs/guides/quickstart.md §1.6.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

import anyio

from ryuu_core.models import AgentResult, Task
from ryuu_workflow.context import ContextScope

__all__ = [
    "HookEvent",
    "HookContext",
    "PreExecuteContext",
    "PostExecuteContext",
    "PreLLMContext",
    "PostLLMContext",
    "PreToolContext",
    "PostToolContext",
    "OnErrorContext",
    "OnCompleteContext",
    "OnBudgetExceededContext",
    "OnRateLimitedContext",
    "HookRegistry",
]

_log = logging.getLogger(__name__)


class HookEvent(StrEnum):
    """Lifecycle events that hooks can subscribe to.

    Phase 9.1 MVP: PRE/POST_EXECUTE, PRE/POST_LLM, ON_ERROR, ON_COMPLETE
    Phase 9.2:    PRE/POST_TOOL, ON_BUDGET_EXCEEDED, ON_RATE_LIMITED
    """

    PRE_EXECUTE = "pre_execute"
    POST_EXECUTE = "post_execute"
    PRE_LLM = "pre_llm"
    POST_LLM = "post_llm"
    PRE_TOOL = "pre_tool"             # Phase 9.2
    POST_TOOL = "post_tool"           # Phase 9.2
    ON_ERROR = "on_error"
    ON_BUDGET_EXCEEDED = "on_budget_exceeded"   # Phase 9.2
    ON_RATE_LIMITED = "on_rate_limited"         # Phase 9.2
    ON_COMPLETE = "on_complete"


# ---------------------------------------------------------------------------
# HookContext variants — typed payload per event
# ---------------------------------------------------------------------------


@dataclass
class HookContext:
    """Base context shared by all events."""

    event: HookEvent
    correlation_id: str
    scope: ContextScope


@dataclass
class PreExecuteContext(HookContext):
    task: Task | None = None


@dataclass
class PostExecuteContext(HookContext):
    task: Task | None = None
    result: AgentResult | None = None


@dataclass
class PreLLMContext(HookContext):
    """Fired BEFORE provider.complete(). `messages` is the prompt being sent."""

    messages: list[Any] = field(default_factory=list)
    model: str = ""


@dataclass
class PostLLMContext(HookContext):
    """Fired AFTER provider.complete(). `response` is the LLM output."""

    response: Any = None
    model: str = ""


@dataclass
class PreToolContext(HookContext):
    """Fired BEFORE tool handler executes. Mutate `args` to modify input."""

    tool_name: str = ""
    args: dict[str, Any] = field(default_factory=dict)

    def replace(self, *, args: dict[str, Any]) -> "PreToolContext":
        """Return new ctx with `args` replaced (for handler mutation)."""
        return PreToolContext(
            event=self.event,
            correlation_id=self.correlation_id,
            scope=self.scope,
            tool_name=self.tool_name,
            args=args,
        )


@dataclass
class PostToolContext(HookContext):
    """Fired AFTER tool handler returns. `result` is the handler's output."""

    tool_name: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    result: Any = None


@dataclass
class OnErrorContext(HookContext):
    error: Exception | None = None
    task: Task | None = None


@dataclass
class OnBudgetExceededContext(HookContext):
    """Fired when CostTracker raises BudgetExceededError."""

    error: Exception | None = None
    task: Task | None = None


@dataclass
class OnRateLimitedContext(HookContext):
    """Fired when RateLimiter raises RateLimitTimeout."""

    error: Exception | None = None
    task: Task | None = None


@dataclass
class OnCompleteContext(HookContext):
    result: AgentResult | None = None


# ---------------------------------------------------------------------------
# HookRegistry — register + fire
# ---------------------------------------------------------------------------


HookHandler = Callable[[HookContext], HookContext | None | Awaitable[HookContext | None]]


class HookRegistry:
    """Owns lifecycle handlers + fires them on events.

    Sequential handlers (default) may:
      - Return None     → no mutation, ctx passes through unchanged
      - Return new ctx  → next handler / agent sees mutated context
      - Raise exception → blocks execution, propagates to caller

    Parallel handlers (`mode="parallel"`):
      - Fire-and-forget — run concurrently in task group
      - Exceptions are SWALLOWED and logged (not propagated)
      - Cannot mutate ctx (return value ignored)
      - Use case: metrics emission, async logging, observability sinks
    """

    def __init__(self) -> None:
        self._handlers: dict[HookEvent, list[tuple[HookHandler, str]]] = defaultdict(list)

    def register(
        self,
        event: HookEvent | str,
        handler: HookHandler,
        *,
        mode: Literal["sequential", "parallel"] = "sequential",
    ) -> None:
        """Register a handler for an event. Mode controls fire semantics."""
        evt = HookEvent(event) if isinstance(event, str) else event
        self._handlers[evt].append((handler, mode))

    def register_dict(
        self,
        mapping: dict[str | HookEvent, list[HookHandler]],
        *,
        mode: Literal["sequential", "parallel"] = "sequential",
    ) -> None:
        """Convenience: register many handlers from a dict.

        ```python
        registry.register_dict({
            "pre_execute": [hook1, hook2],
            "on_error":    [error_logger],
        })
        ```

        All handlers in the dict use the same mode. For mixed modes, call
        register() per handler.
        """
        for event, handlers in mapping.items():
            evt = HookEvent(event) if isinstance(event, str) else event
            for h in handlers:
                self.register(evt, h, mode=mode)

    def has_handlers(self, event: HookEvent) -> bool:
        return bool(self._handlers.get(event))

    async def fire(self, event: HookEvent, ctx: HookContext) -> HookContext:
        """Fire all handlers for an event.

        Sequential handlers run in registration order; each may mutate ctx
        or raise to block.

        Parallel handlers fire concurrently after sequential ones complete.
        They cannot mutate ctx, and exceptions are swallowed + logged.
        """
        entries = self._handlers.get(event, [])
        sequential = [h for h, m in entries if m == "sequential"]
        parallel = [h for h, m in entries if m == "parallel"]

        # 1. Sequential — block, mutate, propagate exceptions
        for handler in sequential:
            result = handler(ctx)
            if asyncio.iscoroutine(result):
                result = await result
            if result is not None and isinstance(result, HookContext):
                ctx = result   # mutation accepted

        # 2. Parallel — fire-and-forget, swallow exceptions
        if parallel:
            async def _fire_one(h: HookHandler) -> None:
                try:
                    res = h(ctx)
                    if asyncio.iscoroutine(res):
                        await res
                except Exception as exc:   # noqa: BLE001
                    _log.warning(
                        "parallel hook %r for event %s swallowed exception: %s",
                        h, event.value, exc,
                    )

            async with anyio.create_task_group() as tg:
                for h in parallel:
                    tg.start_soon(_fire_one, h)

        return ctx
