"""Concrete IScopeResolver implementations.

Two pre-baked resolvers cover the two tenant models we ship by default:
  • DefaultScopeResolver  → per-sender ("channel:sender_id"), multi-tenant
  • SingleTenantResolver  → constant scope_key, single-tenant

Products needing fancier rules (Slack team scope, group-chat shared memory,
hashed pseudonyms for GDPR) implement IScopeResolver themselves.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DefaultScopeResolver:
    """Per-sender scope: each user gets isolated memory + state.

    The right default for **multi-tenant products** (Todo, Flashcard bots).
    Two Telegram users chatting the same bot get fully isolated state.
    """

    async def resolve(self, channel: str, conversation_id: str, sender_id: str) -> str:
        return f"{channel}:{sender_id}"


@dataclass
class SingleTenantResolver:
    """Constant scope: every message lives in the same tenant.

    The right choice for **single-tenant products** (owner-only personal
    assistants). Memory and settings are shared across channels — owner using
    Telegram and CLI see one continuous brain.
    """
    scope_key: str = "owner"

    async def resolve(self, channel: str, conversation_id: str, sender_id: str) -> str:
        return self.scope_key
