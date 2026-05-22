"""WorkingMemoryStore — short-term memory layer (recent observations).

Two backends in one class:
  • In-memory (default, when collection=None) — dict[scope, deque]
  • Persistent (collection=ICollectionStore) — any storage backend

Pass `collection=SqliteCollectionStore(...)` for production. Leave it None
for tests and notebooks — original behavior preserved exactly.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from ryuu_storage_core import ICollectionStore

from ryuu_knowledge_memory.store import MemoryEntry, MemoryLayer


@dataclass
class WorkingMemoryStore:
    layer = MemoryLayer.WORKING
    max_entries: int = 50
    collection: ICollectionStore | None = None
    _store: dict[str, deque[MemoryEntry]] = field(default_factory=dict)

    async def store(
        self,
        content: str,
        scope_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if self.collection is not None:
            await self.collection.append(scope_key, content, metadata or {})
            return
        bucket = self._store.setdefault(scope_key, deque())
        if len(bucket) >= self.max_entries:
            bucket.popleft()
        bucket.append(MemoryEntry(content=content, metadata=metadata or {}))

    async def retrieve(
        self,
        query: str,
        scope_key: str,
        top_k: int = 5,
    ) -> list[MemoryEntry]:
        if self.collection is not None:
            items = await self.collection.list(scope_key, limit=self.max_entries)
            recent = list(reversed(items))[:top_k]
            return [
                MemoryEntry(content=it.content, metadata=it.metadata, created_at=it.created_at)
                for it in recent
            ]
        bucket = list(self._store.get(scope_key, []))
        return list(reversed(bucket))[:top_k]

    async def clear(self, scope_key: str) -> None:
        if self.collection is not None:
            await self.collection.clear(scope_key)
            return
        self._store.pop(scope_key, None)
