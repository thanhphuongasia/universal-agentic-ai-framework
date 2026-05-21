from __future__ import annotations

from typing import Any

from ryuu_knowledge_memory.store import MemoryEntry, MemoryLayer


class EpisodicMemoryStore:
    layer = MemoryLayer.EPISODIC

    def __init__(self, max_entries: int = 500) -> None:
        self._max = max_entries
        self._store: dict[str, list[MemoryEntry]] = {}

    async def store(
        self,
        content: str,
        scope_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        bucket = self._store.setdefault(scope_key, [])
        if len(bucket) >= self._max:
            bucket.pop(0)
        bucket.append(MemoryEntry(content=content, metadata=metadata or {}))

    async def retrieve(
        self,
        query: str,
        scope_key: str,
        top_k: int = 5,
    ) -> list[MemoryEntry]:
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
        self._store.pop(scope_key, None)
