"""CLI (stdin/stdout) channel adapter.

Minimal IChannelAdapter implementation (~80 LOC). Use as:
  • A dev harness for testing IChannelHandler implementations without
    booting a real chat platform.
  • Proof that the messaging interface is genuinely channel-neutral
    (not a Telegram-in-disguise).
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field

from ryuu_messaging_core import (
    IChannelAdapter,
    IncomingMessage,
    OnMessageHandler,
    OutgoingMessage,
)


@dataclass
class CLIAdapter(IChannelAdapter):
    """Reads stdin, writes stdout. Single user, single conversation."""

    channel_name: str = "cli"
    sender_id: str = "local"
    conversation_id: str = "cli:local"
    prompt: str = "you> "
    _stop: asyncio.Event = field(default_factory=asyncio.Event)

    async def start(self, on_message: OnMessageHandler) -> None:
        loop = asyncio.get_running_loop()
        print("[ryuu-messaging] CLI started. Type 'exit' or Ctrl-D to quit.\n")
        while not self._stop.is_set():
            try:
                line = await loop.run_in_executor(None, self._read_input)
            except (EOFError, KeyboardInterrupt):
                break
            if line is None:
                break
            line = line.strip()
            if not line:
                continue
            if line.lower() in {"exit", "quit", ":q"}:
                break

            incoming = IncomingMessage(
                channel=self.channel_name,
                sender_id=self.sender_id,
                conversation_id=self.conversation_id,
                text=line,
            )
            reply = await on_message(incoming)
            await self.send(reply)
        print("\n[ryuu-messaging] CLI stopped.")

    def _read_input(self) -> str | None:
        try:
            return input(self.prompt)
        except EOFError:
            return None

    async def stop(self) -> None:
        self._stop.set()

    async def send(self, msg: OutgoingMessage) -> None:
        sys.stdout.write(f"sensei> {msg.text}\n")
        sys.stdout.flush()
        if msg.actions:
            for i, action in enumerate(msg.actions, 1):
                sys.stdout.write(f"  [{i}] {action.label}\n")
            sys.stdout.flush()

    async def send_typing(self, conversation_id: str) -> None:
        _ = conversation_id  # no typing indicator in CLI
