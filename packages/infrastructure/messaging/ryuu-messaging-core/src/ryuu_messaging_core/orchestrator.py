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

from ryuu_messaging_core.conversation import ConversationManager
from ryuu_messaging_core.messages import IncomingMessage, OutgoingMessage
from ryuu_messaging_core.protocols import IChannelAdapter, IChannelHandler


@dataclass
class ChannelOrchestrator:
    """Lifecycle + dispatch hub. One instance per process."""

    conversation_manager: ConversationManager
    handler: IChannelHandler
    name: str = "Ryuu Sensei"
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
        session = await self.conversation_manager.get_session(msg)
        reply = await self.handler.handle(msg, session)
        await self.conversation_manager.save(session)
        return reply

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
