"""ConversationManager — Layer 2 of the messaging stack.

Sits between IChannelAdapter (Layer 1) and IChannelHandler (Layer 3). Owns:
  • session lookup / creation via ISessionStore
  • scope resolution via IScopeResolver
  • lifecycle helpers (clear, save) so the orchestrator and handler don't
    bypass the resolver

Crucially this class has no idea what product it serves. Multi-tenant Todo
and single-tenant Ryuu both use the same ConversationManager — they differ
only in which IScopeResolver they inject.
"""

from __future__ import annotations

from dataclasses import dataclass

from ryuu_messaging_core.messages import IncomingMessage
from ryuu_messaging_core.protocols import IScopeResolver, Session
from ryuu_messaging_core.session import ISessionStore


@dataclass
class ConversationManager:
    """Routes (channel, sender, conversation) → Session via scope_resolver.

    Inject different ISessionStore impls to swap persistence (memory, JSON,
    SQLite). Inject different IScopeResolver impls to swap tenant model.
    """
    session_store: ISessionStore
    scope_resolver: IScopeResolver

    async def get_session(self, msg: IncomingMessage) -> Session:
        scope_key = await self.scope_resolver.resolve(
            msg.channel, msg.conversation_id, msg.sender_id
        )
        return await self.session_store.load_or_create(
            scope_key=scope_key,
            channel=msg.channel,
            sender_id=msg.sender_id,
            conversation_id=msg.conversation_id,
        )

    async def save(self, session: Session) -> None:
        await self.session_store.save(session)

    async def resolve_scope(
        self, channel: str, sender_id: str, conversation_id: str
    ) -> str:
        """Useful for command handlers (e.g. /clear) that have sender + chat
        but not a full IncomingMessage."""
        return await self.scope_resolver.resolve(channel, conversation_id, sender_id)

    async def clear(self, scope_key: str) -> None:
        await self.session_store.delete(scope_key)
