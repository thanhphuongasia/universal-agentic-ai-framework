"""CLI channel adapter — terminal REPL.

Demonstrates the minimal IChannelAdapter implementation (~80 LOC).
Use as the smoke-test harness while building the core or other adapters.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field

from examples.ryuu_sensei.channel import IChannelAdapter, OnMessageHandler
from examples.ryuu_sensei.messages import IncomingMessage, OutgoingMessage


@dataclass
class CLIAdapter(IChannelAdapter):
    """Reads stdin, writes stdout. Single user, single conversation."""

    channel_name: str = "cli"
    user_id: str = "local"
    conversation_id: str = "cli:local"
    prompt: str = "you> "
    _stop: asyncio.Event = field(default_factory=asyncio.Event)

    async def start(self, on_message: OnMessageHandler) -> None:
        loop = asyncio.get_running_loop()
        print(f"[ryuu-sensei] CLI started. Type 'exit' or Ctrl-D to quit.\n")
        while not self._stop.is_set():
            # readline blocks; run it in a thread so we don't block the event loop
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
                user_id=self.user_id,
                conversation_id=self.conversation_id,
                text=line,
            )
            reply = await on_message(incoming)
            await self.send(reply)
        print("\n[ryuu-sensei] CLI stopped.")

    def _read_input(self) -> str | None:
        try:
            return input(self.prompt)
        except EOFError:
            return None

    async def stop(self) -> None:
        self._stop.set()

    async def send(self, msg: OutgoingMessage) -> None:
        # Plain text rendering for CLI — no markdown processing
        sys.stdout.write(f"sensei> {msg.text}\n")
        sys.stdout.flush()
        if msg.actions:
            for i, action in enumerate(msg.actions, 1):
                sys.stdout.write(f"  [{i}] {action.label}\n")
            sys.stdout.flush()

    async def send_typing(self, conversation_id: str) -> None:
        # No typing indicator in CLI — could print "…" if desired
        _ = conversation_id
