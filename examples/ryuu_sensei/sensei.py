"""RyuuSensei — channel-agnostic orchestrator built on top of `ryuu.Agent`.

Composition (NOT reinvention):
  • LLM call, ReAct loop, cost/audit/rate-limit  → `ryuu.Agent` (Factory API)
  • Conversation memory                          → `SessionStore` (short-term buffer)
  • Channel routing                              → IChannelAdapter registry
  • Session scoping                              → SessionKey = f"{channel}:{user_id}"

The sensei never imports a channel SDK and never touches `ILLMProvider` directly.
It speaks to:
  - channels via `IChannelAdapter`
  - the LLM via `ryuu.Agent.run(message=..., user_id=..., session_id=...)`
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from ryuu import Agent

from examples.ryuu_sensei.channel import IChannelAdapter
from examples.ryuu_sensei.messages import IncomingMessage, OutgoingMessage
from examples.ryuu_sensei.session import SessionStore, Turn, make_session_key

DEFAULT_INSTRUCTIONS = (
    "You are Ryuu Sensei (流先生), a friendly multi-channel AI assistant. "
    "Keep replies concise (under 80 words unless explicitly asked for more). "
    "Use the conversation history provided to maintain context. "
    "Ask clarifying questions when uncertain."
)


def _format_history(history: list[Turn], new_message: str) -> str:
    """Inline prior turns + new user message into a single prompt string.

    Factory Agent.run() is single-shot stateless, so we have to thread
    history through the message text ourselves. Class-based BaseAgent +
    MemoryBackbone (Phase 9.3 in roadmap) is the upgrade path.
    """
    if not history:
        return new_message
    lines = ["Previous conversation:"]
    for turn in history:
        lines.append(f"  {turn.role}: {turn.text}")
    lines.append(f"\nUser now says: {new_message}")
    return "\n".join(lines)


@dataclass
class RyuuSensei:
    """The assistant core. Channel-agnostic; persists for the process lifetime."""

    agent: Agent | None = None
    name: str = "Ryuu Sensei"
    instructions: str = DEFAULT_INSTRUCTIONS
    model: str = "gpt-4o-mini"
    sessions: SessionStore = field(default_factory=SessionStore)
    history_turns: int = 10
    _channels: dict[str, IChannelAdapter] = field(default_factory=dict)
    _tasks: list[asyncio.Task] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.agent is None:
            # Build a default Agent. Requires OPENAI_API_KEY at first .run().
            self.agent = Agent(
                model=self.model,
                instructions=self.instructions,
            )

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
        """Start all registered channels concurrently. Blocks until stop()."""
        if not self._channels:
            raise RuntimeError("No channels registered. Call register_channel() first.")
        self._tasks = [
            asyncio.create_task(ch.start(self.handle_message), name=f"channel:{name}")
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
    # Core message handler — what every channel calls
    # ------------------------------------------------------------------ #
    async def handle_message(self, msg: IncomingMessage) -> OutgoingMessage:
        """Single entry point. Channel-agnostic."""
        assert self.agent is not None  # __post_init__ guarantees this
        key = make_session_key(msg.channel, msg.user_id)

        # 1. Build context-aware prompt (recent turns + new message)
        history = self.sessions.recent(key, n=self.history_turns)
        prompt_text = _format_history(history, msg.text)

        # 2. Delegate to ryuu.Agent — get cost tracking, ReAct loop, audit "for free".
        #    session_id scopes the per-session cost budget + audit trail.
        result = await self.agent.run(
            message=prompt_text,
            user_id=msg.user_id,
            session_id=msg.conversation_id,
            domain=msg.channel,
        )
        reply_text = (result.output or "").strip() or "(no response)"

        # 3. Update short-term memory AFTER successful reply
        self.sessions.append(key, "user", msg.text)
        self.sessions.append(key, "assistant", reply_text)

        return OutgoingMessage(
            conversation_id=msg.conversation_id,
            text=reply_text,
            formatting="markdown",
            metadata={"cost_usd": getattr(result.cost, "usd", 0.0)},
        )

    # ------------------------------------------------------------------ #
    # Session management — adapters call these for /clear-style commands
    # ------------------------------------------------------------------ #
    def clear_session(self, channel: str, user_id: str) -> None:
        """Drop the short-term conversation buffer for one user on one channel."""
        self.sessions.clear(make_session_key(channel, user_id))

    # ------------------------------------------------------------------ #
    # Proactive push — used by cron jobs / external triggers
    # ------------------------------------------------------------------ #
    async def push(self, channel: str, conversation_id: str, text: str) -> None:
        """Send a message without being prompted (proactive notification)."""
        adapter = self._channels.get(channel)
        if adapter is None:
            raise ValueError(f"Channel {channel!r} not registered")
        await adapter.send(OutgoingMessage(
            conversation_id=conversation_id,
            text=text,
        ))
