"""Observability interface for the messaging dispatch layer.

The framework emits structured events automatically at every key decision
point so consumers get full visibility without adding any logging code:

  MessageEvent   — every incoming message (before routing)
  DispatchEvent  — every STOP / STEER / NEW routing decision (with layer,
                   reasoning, model used, and latency)
  TaskEvent      — task lifecycle: start / finish / cancel
  ErrorEvent     — handler or classifier errors

Protocol::

    class IDispatchLogger(Protocol):
        def on_message(self, event: MessageEvent) -> None: ...
        def on_dispatch(self, event: DispatchEvent) -> None: ...
        def on_task(self, event: TaskEvent) -> None: ...
        def on_error(self, event: ErrorEvent) -> None: ...

Default impl::

    # In main_ryuu.py — zero extra wiring: plugs into _setup_logging()
    from ryuu_messaging_core import StandardDispatchLogger, ScopeDispatcher
    dispatcher = ScopeDispatcher(
        ...,
        logger=StandardDispatchLogger(),   # → ~/.ryuu/ryuu.log
    )

Swap to any backend (OTel, DB, custom) by implementing IDispatchLogger.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# Event dataclasses
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MessageEvent:
    """Emitted for every incoming user message before routing."""
    scope_key: str
    text_preview: str       # first 80 chars, no PII trimming (caller's responsibility)
    active_task: bool       # True if a handler task was already running
    ts: str = field(default_factory=_now)


@dataclass(frozen=True)
class DispatchEvent:
    """Emitted for every STOP / STEER / NEW routing decision."""
    scope_key: str
    label: str              # "STOP" | "STEER" | "NEW"
    message_preview: str
    task_summary: str
    layer: str              # "heuristic" | "llm" | "fallback"
    reasoning: str = ""     # LLM chain-of-thought (populated when layer="llm")
    model: str = ""         # model used by classifier (populated when layer="llm")
    latency_ms: float = 0.0
    ts: str = field(default_factory=_now)


@dataclass(frozen=True)
class TaskEvent:
    """Emitted on task start, finish, or cancel."""
    scope_key: str
    kind: str               # "start" | "finish" | "cancel"
    task_summary: str = ""
    ts: str = field(default_factory=_now)


@dataclass(frozen=True)
class ErrorEvent:
    """Emitted on handler or classifier errors."""
    scope_key: str
    exc_type: str
    message: str
    context: str = ""
    ts: str = field(default_factory=_now)


# ─────────────────────────────────────────────────────────────────────────────
# Protocol
# ─────────────────────────────────────────────────────────────────────────────

@runtime_checkable
class IDispatchLogger(Protocol):
    """Observability contract for the messaging dispatch layer.

    Implement this (not the concrete classes) to route events to any backend
    — rotating file, structured JSON, OpenTelemetry, database — without
    touching framework internals.
    """

    def on_message(self, event: MessageEvent) -> None: ...
    def on_dispatch(self, event: DispatchEvent) -> None: ...
    def on_task(self, event: TaskEvent) -> None: ...
    def on_error(self, event: ErrorEvent) -> None: ...


# ─────────────────────────────────────────────────────────────────────────────
# Default implementations
# ─────────────────────────────────────────────────────────────────────────────

class StandardDispatchLogger:
    """Default implementation — writes structured lines to Python logging.

    Plugs into whatever handler _setup_logging() configures in main_ryuu.py
    (stdout + RotatingFileHandler at ~/.ryuu/ryuu.log) — zero extra wiring.

    Log format examples::

        INFO  ryuu.dispatch — MSG   scope=owner active=True preview='Viết bài...'
        INFO  ryuu.dispatch — DISPATCH scope=owner label=STEER layer=llm
                              latency=203ms model=gpt-4o-mini task='...' reason='...'
        INFO  ryuu.dispatch — TASK  scope=owner kind=start summary='...'
        ERROR ryuu.dispatch — ERROR scope=owner exc=TypeError msg='...' ctx='...'
    """

    def __init__(self, logger_name: str = "ryuu.dispatch") -> None:
        self._log = logging.getLogger(logger_name)

    def on_message(self, event: MessageEvent) -> None:
        self._log.info(
            "MSG   scope=%s active=%s preview=%r",
            event.scope_key, event.active_task, event.text_preview,
        )

    def on_dispatch(self, event: DispatchEvent) -> None:
        self._log.info(
            "DISPATCH scope=%s label=%s layer=%s latency=%.0fms model=%s"
            " task=%r reason=%r",
            event.scope_key, event.label, event.layer, event.latency_ms,
            event.model or "-",
            event.task_summary[:60],
            event.reasoning[:120],
        )

    def on_task(self, event: TaskEvent) -> None:
        self._log.info(
            "TASK  scope=%s kind=%s summary=%r",
            event.scope_key, event.kind, event.task_summary[:60],
        )

    def on_error(self, event: ErrorEvent) -> None:
        self._log.error(
            "ERROR scope=%s exc=%s msg=%s ctx=%s",
            event.scope_key, event.exc_type, event.message, event.context,
        )


class NullDispatchLogger:
    """No-op — use when logging is explicitly disabled or in tests."""

    def on_message(self, event: MessageEvent) -> None: pass
    def on_dispatch(self, event: DispatchEvent) -> None: pass
    def on_task(self, event: TaskEvent) -> None: pass
    def on_error(self, event: ErrorEvent) -> None: pass


# ─────────────────────────────────────────────────────────────────────────────
# Internal helper
# ─────────────────────────────────────────────────────────────────────────────

class _Timer:
    """Monotonic timer. Call .elapsed_ms() to get ms since construction."""
    __slots__ = ("_start",)

    def __init__(self) -> None:
        self._start = time.monotonic()

    def elapsed_ms(self) -> float:
        return (time.monotonic() - self._start) * 1000.0


__all__ = [
    "DispatchEvent",
    "ErrorEvent",
    "IDispatchLogger",
    "MessageEvent",
    "NullDispatchLogger",
    "StandardDispatchLogger",
    "TaskEvent",
    "_Timer",
]
