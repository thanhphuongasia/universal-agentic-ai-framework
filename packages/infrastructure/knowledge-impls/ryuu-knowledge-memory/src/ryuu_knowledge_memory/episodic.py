"""EpisodicMemoryStore — long-term observations + keyword-overlap retrieval.

Same two-backend pattern as WorkingMemoryStore.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ryuu_storage_core import ICollectionStore

from ryuu_knowledge_memory.store import MemoryEntry, MemoryLayer


@dataclass
class EpisodicMemoryStore:
    layer = MemoryLayer.EPISODIC
    max_entries: int = 500
    collection: ICollectionStore | None = None
    _store: dict[str, list[MemoryEntry]] = field(default_factory=dict)

    async def store(
        self,
        content: str,
        scope_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if self.collection is not None:
            await self.collection.append(scope_key, content, metadata or {})
            return
        bucket = self._store.setdefault(scope_key, [])
        if len(bucket) >= self.max_entries:
            bucket.pop(0)
        bucket.append(MemoryEntry(content=content, metadata=metadata or {}))

    async def retrieve(
        self,
        query: str,
        scope_key: str,
        top_k: int = 5,
    ) -> list[MemoryEntry]:
        if self.collection is not None:
            items = await self.collection.search(scope_key, query, top_k=top_k)
            return [
                MemoryEntry(content=it.content, metadata=it.metadata, created_at=it.created_at)
                for it in items
            ]

        bucket = self._store.get(scope_key, [])
        if not query.strip():
            return bucket[-top_k:]

        query_words = set(query.lower().split())
        scored: list[MemoryEntry] = []
        for entry in bucket:
            entry_words = set(entry.content.lower().split())
            overlap = len(query_words & entry_words)
            if overlap > 0:
                score = overlap / len(query_words)
                scored.append(MemoryEntry(
                    content=entry.content,
                    score=score,
                    created_at=entry.created_at,
                    metadata=entry.metadata,
                ))

        scored.sort(key=lambda e: e.score, reverse=True)
        return scored[:top_k]

    async def clear(self, scope_key: str) -> None:
        if self.collection is not None:
            await self.collection.clear(scope_key)
            return
        self._store.pop(scope_key, None)
