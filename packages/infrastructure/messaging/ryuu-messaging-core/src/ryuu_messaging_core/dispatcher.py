"""ScopeDispatcher — per-scope concurrency control for ChannelOrchestrator.

Three primitives + one state machine:

  CancelToken      asyncio.Event; set to abort current handler task (or cancel
                   the asyncio.Task directly — both approaches work)
  SteeringContext  asyncio.Queue; accumulates steer messages while agent runs;
                   drained at the start of the next handle() call
  MessageClassifier
                   Two-layer router:
                     1. Keyword heuristics (free, < 1ms)
                     2. LLM CoT via dispatch/v3.yaml (gpt-4o-mini, ~200ms)
  ScopeDispatcher  Per-scope state machine wired into ChannelOrchestrator

Wiring example:

    dispatcher = ScopeDispatcher(
        classifier=MessageClassifier(provider=llm_provider),
        provider=llm_provider,
    )
    orchestrator = ChannelOrchestrator(
        ...,
        dispatcher=dispatcher,
    )
"""

from __future__ import annotations

import asyncio
import enum
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Primitives
# ─────────────────────────────────────────────────────────────────────────────

class DispatchLabel(str, enum.Enum):
    """Routing decision for a message that arrives while a task is running."""
    STOP  = "STOP"   # cancel current task; generate stop summary
    STEER = "STEER"  # inject context into current task; ack quickly
    NEW   = "NEW"    # unrelated; queue or reject until task finishes


@dataclass
class CancelToken:
    """Cooperative cancel signal checked between ReAct steps.

    Handlers that support fine-grained cancellation check .is_cancelled()
    between tool calls. Handlers that don't will be cancelled at the next
    asyncio yield point when the wrapping Task is cancelled.
    """
    _event: asyncio.Event = field(default_factory=asyncio.Event)

    def set(self) -> None:
        self._event.set()

    def reset(self) -> None:
        self._event.clear()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    async def wait(self) -> None:
        await self._event.wait()


@dataclass
class SteeringContext:
    """Accumulates steer messages while agent runs.

    Drained by RyuuHandler at the start of each handle() call so the
    steer content is injected into the next LLM prompt.
    """
    _queue: asyncio.Queue[str] = field(default_factory=asyncio.Queue)

    def add(self, text: str) -> None:
        self._queue.put_nowait(text)

    def drain(self) -> list[str]:
        """Return all pending steer messages and clear the queue."""
        items: list[str] = []
        while not self._queue.empty():
            try:
                items.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return items

    def is_empty(self) -> bool:
        return self._queue.empty()


# ─────────────────────────────────────────────────────────────────────────────
# Per-scope state
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ScopeState:
    """Live concurrency state for one scope while a task is running."""
    cancel_token: CancelToken     = field(default_factory=CancelToken)
    steer_ctx:    SteeringContext = field(default_factory=SteeringContext)
    task_summary: str = ""
    _task: asyncio.Task | None = field(default=None, init=False, repr=False)

    def attach_task(self, task: asyncio.Task) -> None:
        self._task = task

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def cancel_task(self) -> bool:
        """Request asyncio cancellation of the running task. Returns True if cancelled."""
        if self._task and not self._task.done():
            self._task.cancel()
            return True
        return False

    def reset(self) -> None:
        self._task        = None
        self.cancel_token  = CancelToken()
        self.steer_ctx     = SteeringContext()
        self.task_summary  = ""


# ─────────────────────────────────────────────────────────────────────────────
# Classifier
# ─────────────────────────────────────────────────────────────────────────────

_STOP_PHRASES: frozenset[str] = frozenset([
    # English
    "stop", "cancel", "abort", "quit", "halt",
    "never mind", "nevermind", "forget it", "drop it", "skip it",
    # Vietnamese
    "dừng", "thôi", "hủy", "bỏ qua", "bỏ đi", "dừng lại", "thôi đi",
])


class MessageClassifier:
    """Two-layer message router.

    Layer 1 — Keyword heuristics (free): catches obvious STOP signals in
    short messages without spending a token.

    Layer 2 — LLM CoT (paid): gpt-4o-mini with chain-of-thought reasoning
    from dispatch/v3.yaml; handles ambiguous STEER vs NEW edge cases.

    Args:
        provider:        ryuu_providers_core.ILLMProvider. Required for Layer 2.
                         Without it, classifier falls back to heuristics-only
                         and defaults ambiguous messages to NEW.
        prompt_registry: PromptRegistry with ryuu-messaging-core prompts root
                         already included. Optional — if absent, a private
                         registry is built from the package's prompts/ dir.
    """

    def __init__(
        self,
        provider: Any | None = None,
        prompt_registry: Any | None = None,
    ) -> None:
        self._provider = provider
        self._registry = prompt_registry
        self._cfg: Any = None

    # ------------------------------------------------------------------
    def _load_cfg(self) -> Any | None:
        if self._cfg is not None:
            return self._cfg
        try:
            from ryuu_prompts import PromptRegistry
            pkg_prompts = Path(__file__).parent / "prompts"
            reg = PromptRegistry(prompts_roots=[pkg_prompts])
            self._cfg = reg.load("dispatch", "v3")
            return self._cfg
        except Exception as exc:
            log.debug("dispatch/v3 config unavailable: %s", exc)
            return None

    # ------------------------------------------------------------------
    async def classify(self, message: str, task_summary: str) -> DispatchLabel:
        """Classify a message relative to the currently-running task."""
        stripped   = message.strip()
        lower      = stripped.lower()
        word_count = len(stripped.split())

        # ── Layer 1: heuristics — fast path for obvious STOP ─────────
        if word_count <= 8:
            for phrase in _STOP_PHRASES:
                if phrase in lower:
                    return DispatchLabel.STOP

        # ── Layer 2: LLM CoT ─────────────────────────────────────────
        if self._provider is not None:
            cfg = self._load_cfg()
            if cfg is not None:
                return await self._llm_classify(stripped, task_summary, cfg)

        # ── Fallback: no LLM → NEW ───────────────────────────────────
        return DispatchLabel.NEW

    async def _llm_classify(self, message: str, task_summary: str, cfg: Any) -> DispatchLabel:
        try:
            from ryuu_providers.llm import CompletionRequest, Message

            tpl = cfg.prompts["classify"]
            request = CompletionRequest(
                model=cfg.model,
                messages=[
                    Message(role="system", content=tpl.render_system()),
                    Message(role="user",   content=tpl.render_user(
                        task_summary=task_summary, message=message,
                    )),
                ],
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
            )
            response = await self._provider.complete(request)
            raw      = (response.content or "").strip()
            data     = json.loads(raw)
            return DispatchLabel(str(data.get("label", "NEW")).upper())
        except Exception as exc:
            log.warning("LLM classify failed (%s) — defaulting to NEW", exc)
            return DispatchLabel.NEW


# ─────────────────────────────────────────────────────────────────────────────
# ScopeDispatcher
# ─────────────────────────────────────────────────────────────────────────────

class ScopeDispatcher:
    """Per-scope state machine. One instance shared across all scopes.

    Call sequence inside ChannelOrchestrator._on_message:

        label, state = await dispatcher.route(msg.text, scope_key)

        STOP  → cancel task, await cleanup, generate stop_summary reply
        STEER → state.steer_ctx.add(msg.text), ack reply
        NEW with state  → immediate "I'll handle that later" reply
        NEW without state → normal path: start_task() → run handler → finish_task()
    """

    def __init__(
        self,
        classifier: MessageClassifier | None = None,
        provider: Any | None = None,
    ) -> None:
        self._classifier = classifier or MessageClassifier()
        self._provider   = provider
        self._states: dict[str, ScopeState] = {}

    # ------------------------------------------------------------------
    # State accessors
    # ------------------------------------------------------------------
    def get_state(self, scope_key: str) -> ScopeState:
        if scope_key not in self._states:
            self._states[scope_key] = ScopeState()
        return self._states[scope_key]

    def is_running(self, scope_key: str) -> bool:
        s = self._states.get(scope_key)
        return s is not None and s.is_running()

    # ------------------------------------------------------------------
    # Task lifecycle
    # ------------------------------------------------------------------
    async def start_task(
        self,
        scope_key: str,
        task: asyncio.Task,
        *,
        first_message: str = "",
    ) -> ScopeState:
        """Register a running handler task for this scope.

        Attaches the task immediately (so is_running() returns True right
        away) then generates a 1-sentence task_summary via LLM (Option A).
        """
        state = self.get_state(scope_key)
        state.reset()
        state.attach_task(task)                              # register first
        state.task_summary = await self._summarize(first_message)   # then summarize
        return state

    def finish_task(self, scope_key: str) -> None:
        """Mark scope as idle. Called in a finally block after the task completes."""
        s = self._states.get(scope_key)
        if s:
            s.reset()

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------
    async def route(
        self, message: str, scope_key: str,
    ) -> tuple[DispatchLabel, ScopeState | None]:
        """Route an incoming message for the given scope.

        Returns:
            (NEW,   None)  — no task running; caller starts one normally
            (STOP,  state) — caller cancels task + generates stop reply
            (STEER, state) — caller adds to steer_ctx + acks quickly
            (NEW,   state) — unrelated; caller responds "I'll get to that"
        """
        if not self.is_running(scope_key):
            return DispatchLabel.NEW, None

        state = self.get_state(scope_key)
        label = await self._classifier.classify(message, state.task_summary)
        return label, state

    # ------------------------------------------------------------------
    # LLM helpers
    # ------------------------------------------------------------------
    async def _summarize(self, message: str) -> str:
        """1-sentence task summary via LLM. Falls back to first 80 chars."""
        if not message or self._provider is None:
            return message[:80]
        cfg = self._classifier._load_cfg()
        if cfg is None:
            return message[:80]
        try:
            from ryuu_providers.llm import CompletionRequest, Message
            tpl = cfg.prompts["task_summarize"]
            request = CompletionRequest(
                model=cfg.model,
                messages=[
                    Message(role="system", content=tpl.render_system()),
                    Message(role="user",   content=tpl.render_user(user_message=message)),
                ],
                temperature=0.0,
                max_tokens=40,
            )
            response = await self._provider.complete(request)
            return (response.content or "").strip() or message[:80]
        except Exception:
            return message[:80]

    async def stop_summary(self, scope_key: str, *, progress: str = "") -> str:
        """Natural-language stop acknowledgement via LLM."""
        state        = self._states.get(scope_key)
        task_summary = (state.task_summary if state else "") or "the current task"
        if not progress:
            progress = "Task was interrupted before completion."

        if self._provider is None:
            return f"Stopped. Task: {task_summary}"

        cfg = self._classifier._load_cfg()
        if cfg is None:
            return f"Stopped. Task: {task_summary}"

        try:
            from ryuu_providers.llm import CompletionRequest, Message
            tpl = cfg.prompts["stop_summary"]
            request = CompletionRequest(
                model=cfg.model,
                messages=[
                    Message(role="system", content=tpl.render_system()),
                    Message(role="user",   content=tpl.render_user(
                        task_summary=task_summary, progress=progress,
                    )),
                ],
                temperature=0.0,
                max_tokens=cfg.max_tokens,
            )
            response = await self._provider.complete(request)
            return (response.content or "").strip() or f"Stopped. Task: {task_summary}"
        except Exception:
            return f"Stopped. Task: {task_summary}"


__all__ = [
    "CancelToken",
    "DispatchLabel",
    "MessageClassifier",
    "ScopeDispatcher",
    "ScopeState",
    "SteeringContext",
]
