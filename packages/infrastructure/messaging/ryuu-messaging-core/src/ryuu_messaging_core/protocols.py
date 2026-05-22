"""Channel-layer contracts (Layer 1 + Layer 2 boundary types).

Three protocols + one value type:
  • IChannelAdapter (Layer 1) — speaks one chat platform
  • IChannelHandler (Layer 3) — owns product logic
  • IScopeResolver  (Layer 2) — identity → tenant key
  • Session + Turn  (Layer 2) — short-term conversation state value object

The orchestrator and adapters never import each other directly. They
communicate through these protocols.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

from ryuu_messaging_core.messages import IncomingMessage, OutgoingMessage

# Handler returns one reply. Streaming (AsyncIterator) is deferred.
OnMessageHandler = Callable[[IncomingMessage], Awaitable[OutgoingMessage]]


# ----------------------------------------------------------------------------
# Layer 1 — Adapter contract (one impl per chat platform)
# ----------------------------------------------------------------------------

@runtime_checkable
class IChannelAdapter(Protocol):
    """Bidirectional bridge between a chat platform and the orchestrator."""

    channel_name: str   # "telegram" | "slack" | "cli" | ...

    async def start(self, on_message: OnMessageHandler) -> None:
        """Begin listening. For each incoming user message:
           1. translate native payload → IncomingMessage
           2. await on_message(msg) → OutgoingMessage
           3. send the reply back via the platform's native API.

        Should block (or run forever as an asyncio task) until stop().
        """
        ...

    async def stop(self) -> None: ...
    async def send(self, msg: OutgoingMessage) -> None: ...
    async def send_typing(self, conversation_id: str) -> None: ...


# ----------------------------------------------------------------------------
# Layer 2 — Scope resolver: identity → tenant key
# ----------------------------------------------------------------------------

@runtime_checkable
class IScopeResolver(Protocol):
    """Maps (channel, conversation_id, sender_id) → scope_key.

    The single source of truth for "what tenant does this message belong to".
    EVERY memory write/read passes through a scope_key — losing the key means
    cross-tenant leak.
    """

    async def resolve(self, channel: str, conversation_id: str, sender_id: str) -> str:
        ...


# ----------------------------------------------------------------------------
# Layer 2 — Session value type
# ----------------------------------------------------------------------------

@dataclass
class Turn:
    role: str       # "user" | "assistant"
    text: str


@dataclass
class Session:
    """A conversation in flight. Identity + recent turns + extension bag.

    Handlers READ session.history to build prompts, and MUTATE session.history
    after each reply. ConversationManager persists the session through the
    ISessionStore afterwards.
    """
    scope_key: str
    channel: str
    sender_id: str
    conversation_id: str
    history: list[Turn] = field(default_factory=list)
    max_turns: int = 20
    extra: dict[str, Any] = field(default_factory=dict)
    # ↑ `extra` is the per-session open bag — pending HITL question,
    # multi-turn clarify state, etc. Handler-defined, store-opaque.

    def append(self, role: str, text: str) -> None:
        self.history.append(Turn(role=role, text=text))
        if len(self.history) > self.max_turns:
            self.history = self.history[-self.max_turns:]

    def recent(self, n: int | None = None) -> list[Turn]:
        if n is None:
            return list(self.history)
        return list(self.history)[-n:]


# ----------------------------------------------------------------------------
# Layer 3 — Handler contract (one impl per product)
# ----------------------------------------------------------------------------

@runtime_checkable
class IChannelHandler(Protocol):
    """Product-layer message processor.

    The adapter doesn't know if `self` is a TodoHandler, RyuuHandler or
    FlashHandler. Orchestrator builds Session via ConversationManager,
    hands (msg, session) to the handler, persists session afterwards.
    """

    async def handle(self, msg: IncomingMessage, session: Session) -> OutgoingMessage:
        ...
