"""WorkingMemoryStore — bounded FIFO short-term memory — P3-T03."""

from __future__ import annotations

from collections import deque
from typing import Any

from uaaf.knowledge.memory.store import MemoryEntry, MemoryLayer


class WorkingMemoryStore:
    """Bounded FIFO deque per scope; oldest entry evicted when full."""

    layer = MemoryLayer.WORKING

    def __init__(self, max_entries: int = 50) -> None:
        self._max = max_entries
        self._store: dict[str, deque[MemoryEntry]] = {}

    async def store(
        self,
        content: str,
        scope_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        bucket = self._store.setdefault(scope_key, deque())
        if len(bucket) >= self._max:
            bucket.popleft()
        bucket.append(MemoryEntry(content=content, metadata=metadata or {}))

    async def retrieve(
        self,
        query: str,
        scope_key: str,
        top_k: int = 5,
    ) -> list[MemoryEntry]:
        bucket = list(self._store.get(scope_key, []))
        # Most-recent-first
        return list(reversed(bucket))[:top_k]

    async def clear(self, scope_key: str) -> None:
        self._store.pop(scope_key, None)
