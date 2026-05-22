"""Session storage — protocol + backends.

Two layers:
  • `ISessionStore`     legacy protocol (kept for back-compat & cheap impls)
  • `KVSessionStore`    generic impl that takes any `IKVStore` — this is the
                         path forward (SQLite / Redis / Postgres swap = 1 line)

`InMemorySessionStore` is a thin alias around `KVSessionStore(InMemoryKVStore())`
so existing tests keep working with `InMemorySessionStore()` zero-arg calls.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Protocol, runtime_checkable

from ryuu_storage_core import IKVStore

from ryuu_messaging_core.protocols import Session, Turn  # noqa: F401  (re-export Turn)

SessionKey = str


@runtime_checkable
class ISessionStore(Protocol):
    """Original Session persistence boundary. Kept stable so existing code
    (ConversationManager, products) doesn't depend on the storage rewrite.
    """

    async def load_or_create(
        self,
        scope_key: str,
        channel: str,
        sender_id: str,
        conversation_id: str,
    ) -> Session: ...

    async def save(self, session: Session) -> None: ...
    async def delete(self, scope_key: str) -> None: ...
    async def all_keys(self) -> Iterable[str]: ...


# ---------------------------------------------------------------------------
# KVSessionStore — generic; pluggable via IKVStore
# ---------------------------------------------------------------------------

def _serialize(session: Session) -> str:
    payload: dict[str, Any] = {
        "scope_key": session.scope_key,
        "channel": session.channel,
        "sender_id": session.sender_id,
        "conversation_id": session.conversation_id,
        "history": [asdict(t) for t in session.history],
        "max_turns": session.max_turns,
        "extra": session.extra,
    }
    return json.dumps(payload, ensure_ascii=False)


def _deserialize(blob: str) -> Session:
    p = json.loads(blob)
    return Session(
        scope_key=p["scope_key"],
        channel=p["channel"],
        sender_id=p["sender_id"],
        conversation_id=p["conversation_id"],
        history=[Turn(**t) for t in p.get("history", [])],
        max_turns=int(p.get("max_turns", 20)),
        extra=p.get("extra", {}),
    )


@dataclass
class KVSessionStore:
    """Session persistence via any IKVStore. Backend-agnostic.

    Picks up SQLite, Redis, Postgres, S3, … by swapping the `kv=` injected
    instance. No code change in ConversationManager / handlers.
    """
    kv: IKVStore
    max_turns: int = 20

    async def load_or_create(
        self,
        scope_key: str,
        channel: str,
        sender_id: str,
        conversation_id: str,
    ) -> Session:
        blob = await self.kv.get(scope_key)
        if blob is not None:
            try:
                return _deserialize(blob)
            except (json.JSONDecodeError, KeyError):
                # Corrupted row — fall through and overwrite with fresh session
                pass
        return Session(
            scope_key=scope_key,
            channel=channel,
            sender_id=sender_id,
            conversation_id=conversation_id,
            max_turns=self.max_turns,
        )

    async def save(self, session: Session) -> None:
        await self.kv.put(session.scope_key, _serialize(session))

    async def delete(self, scope_key: str) -> None:
        await self.kv.delete(scope_key)

    async def all_keys(self) -> Iterable[str]:
        return await self.kv.keys()


# ---------------------------------------------------------------------------
# InMemorySessionStore — back-compat alias
# ---------------------------------------------------------------------------

@dataclass
class InMemorySessionStore:
    """Zero-arg construction → in-memory dict. Same surface as the old impl.

    Internally this is `KVSessionStore(kv=InMemoryKVStore())` — kept as a
    distinct class so user code that imports it by name continues to work.
    """
    max_turns: int = 20
    _impl: KVSessionStore | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        # Lazy import so ryuu-storage-memory isn't a hard runtime dep — only
        # imported when someone constructs InMemorySessionStore.
        from ryuu_storage_memory import InMemoryKVStore
        self._impl = KVSessionStore(kv=InMemoryKVStore(table="sessions"), max_turns=self.max_turns)

    async def load_or_create(
        self,
        scope_key: str,
        channel: str,
        sender_id: str,
        conversation_id: str,
    ) -> Session:
        assert self._impl is not None
        return await self._impl.load_or_create(scope_key, channel, sender_id, conversation_id)

    async def save(self, session: Session) -> None:
        assert self._impl is not None
        await self._impl.save(session)

    async def delete(self, scope_key: str) -> None:
        assert self._impl is not None
        await self._impl.delete(scope_key)

    async def all_keys(self) -> Iterable[str]:
        assert self._impl is not None
        return await self._impl.all_keys()
