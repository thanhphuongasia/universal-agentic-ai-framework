"""IChannelAdapter — protocol every channel adapter must implement.

Implementing a new channel = implementing this protocol. Should be ~100–150 LOC
per channel (see cli_adapter.py for the minimal reference implementation).
"""

from __future__ import annotations

from typing import Awaitable, Callable, Protocol, runtime_checkable

from examples.ryuu_sensei.messages import IncomingMessage, OutgoingMessage

# Callback signature: receive normalized message, return reply
OnMessageHandler = Callable[[IncomingMessage], Awaitable[OutgoingMessage]]


@runtime_checkable
class IChannelAdapter(Protocol):
    """Bidirectional bridge between a chat platform and the Sensei core."""

    channel_name: str   # "telegram" | "slack" | ...

    async def start(self, on_message: OnMessageHandler) -> None:
        """Begin listening. For each incoming user message:
           1. translate native payload → IncomingMessage
           2. await on_message(msg) → OutgoingMessage
           3. send the reply back via the platform's native API.

        This call should block (or run forever as an asyncio task) until stop().
        """
        ...

    async def stop(self) -> None:
        """Stop listening, close connections, flush queues."""
        ...

    async def send(self, msg: OutgoingMessage) -> None:
        """Push a message to a conversation without being prompted.

        Used for proactive notifications (cron jobs, alerts). Must look up
        the chat/conversation by `msg.conversation_id`.
        """
        ...

    async def send_typing(self, conversation_id: str) -> None:
        """Show 'is typing…' indicator if the platform supports it."""
        ...
