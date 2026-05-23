"""ChannelOrchestrator — wires adapters, ConversationManager, and handler.

Persistent asyncio process. Channel adapters register, then `start()` runs
all adapters concurrently. For each incoming message the dispatch path is:

    adapter → orchestrator._on_message → CM.get_session → handler.handle
        → CM.save → adapter.send

The orchestrator NEVER imports a channel SDK and NEVER imports product logic.
It only talks to abstract protocols.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from ryuu_messaging_core.conversation import ConversationManager
from ryuu_messaging_core.dispatcher import DispatchLabel, ScopeDispatcher
from ryuu_messaging_core.messages import IncomingMessage, OutgoingMessage
from ryuu_messaging_core.protocols import IChannelAdapter, IChannelHandler


@dataclass
class ChannelOrchestrator:
    """Lifecycle + dispatch hub. One instance per process."""

    conversation_manager: ConversationManager
    handler: IChannelHandler
    name: str = "Ryuu Sensei"
    dispatcher: ScopeDispatcher | None = None
    _channels: dict[str, IChannelAdapter] = field(default_factory=dict)
    _tasks: list[asyncio.Task] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    # Channel registration
    # ------------------------------------------------------------------ #
    def register_channel(self, adapter: IChannelAdapter) -> None:
        if adapter.channel_name in self._channels:
            raise ValueError(f"Channel {adapter.channel_name!r} already registered")
        self._channels[adapter.channel_name] = adapter

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    async def start(self) -> None:
        if not self._channels:
            raise RuntimeError("No channels registered. Call register_channel() first.")
        self._tasks = [
            asyncio.create_task(ch.start(self._on_message), name=f"channel:{name}")
            for name, ch in self._channels.items()
        ]
        await asyncio.gather(*self._tasks, return_exceptions=False)

    async def stop(self) -> None:
        await asyncio.gather(
            *(ch.stop() for ch in self._channels.values()),
            return_exceptions=True,
        )
        for t in self._tasks:
            t.cancel()

    # ------------------------------------------------------------------ #
    # Dispatch — single entry point every adapter calls
    # ------------------------------------------------------------------ #
    async def _on_message(self, msg: IncomingMessage) -> OutgoingMessage:
        session   = await self.conversation_manager.get_session(msg)
        scope_key = session.scope_key

        # ── Dispatcher routing (only when a task is already running) ──
        if self.dispatcher is not None and self.dispatcher.is_running(scope_key):
            label, state = await self.dispatcher.route(msg.text, scope_key)

            if label == DispatchLabel.STOP and state is not None:
                state.cancel_task()
                # Give the task 2 s to handle CancelledError cleanly.
                # Use shield so this wait can't be itself cancelled.
                # DON'T call finish_task here — _run_handler's finally does it.
                if state._task is not None:
                    try:
                        await asyncio.wait_for(
                            asyncio.shield(state._task), timeout=2.0,
                        )
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        pass
                # task_summary is still intact (finish_task not yet called)
                stop_text = await self.dispatcher.stop_summary(scope_key)
                return OutgoingMessage(
                    conversation_id=msg.conversation_id, text=stop_text,
                )

            if label == DispatchLabel.STEER and state is not None:
                state.steer_ctx.add(msg.text)
                return OutgoingMessage(
                    conversation_id=msg.conversation_id,
                    text="Got it — I'll keep that in mind for the current task.",
                )

            # NEW while running — let the user know
            return OutgoingMessage(
                conversation_id=msg.conversation_id,
                text="Still working on the previous task. I'll handle this one right after.",
            )

        # ── Normal path — run handler (tracked by dispatcher if present) ──
        return await self._run_handler(msg, session)

    async def _run_handler(
        self, msg: IncomingMessage, session: Any,
    ) -> OutgoingMessage:
        """Execute handler + save session; register with dispatcher when present."""

        async def _core() -> OutgoingMessage:
            reply = await self.handler.handle(msg, session)
            await self.conversation_manager.save(session)
            return reply

        if self.dispatcher is None:
            return await _core()

        scope_key = session.scope_key
        # Store the ScopeState OBJECT (not field copies) so that when
        # start_task resets the state, handlers always drain the correct
        # (post-reset) steer_ctx regardless of scheduling order.
        state = self.dispatcher.get_state(scope_key)
        session.extra["_dispatcher_state"] = state

        task = asyncio.create_task(_core(), name=f"handler:{scope_key}")
        await self.dispatcher.start_task(scope_key, task, first_message=msg.text)
        # After start_task: state.steer_ctx / cancel_token are new objects;
        # session.extra["_dispatcher_state"] IS state, so handlers see them.
        try:
            return await task
        except asyncio.CancelledError:
            # Task was cancelled by a STOP that arrived during _summarize window
            return OutgoingMessage(conversation_id=msg.conversation_id, text="")
        finally:
            self.dispatcher.finish_task(scope_key)

    # ------------------------------------------------------------------ #
    # Helpers exposed to adapter command callbacks (/clear etc.)
    # ------------------------------------------------------------------ #
    async def clear_scope(
        self, channel: str, sender_id: str, conversation_id: str
    ) -> str:
        """Resolve scope from raw IDs and wipe the corresponding session.

        Returns the scope_key that was cleared, so the caller (e.g. handler
        wanting to reset per-scope stats) can hook in.
        """
        scope_key = await self.conversation_manager.resolve_scope(
            channel=channel, sender_id=sender_id, conversation_id=conversation_id
        )
        await self.conversation_manager.clear(scope_key)
        return scope_key

    async def push(self, channel: str, conversation_id: str, text: str) -> None:
        """Proactive push — for cron jobs / external alerts."""
        adapter = self._channels.get(channel)
        if adapter is None:
            raise ValueError(f"Channel {channel!r} not registered")
        await adapter.send(OutgoingMessage(conversation_id=conversation_id, text=text))
