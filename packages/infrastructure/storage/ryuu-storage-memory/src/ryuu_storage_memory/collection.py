"""InMemoryCollectionStore — list-backed ICollectionStore for tests and dev."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from ryuu_storage_core import Item


@dataclass
class InMemoryCollectionStore:
    table: str = "default"
    _data: dict[str, list[Item]] = field(default_factory=dict)

    def _bucket(self, scope_key: str) -> list[Item]:
        return self._data.setdefault(scope_key, [])

    async def append(
        self,
        scope_key: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        item_id = uuid.uuid4().hex
        self._bucket(scope_key).append(Item(
            id=item_id,
            scope_key=scope_key,
            content=content,
            metadata=metadata or {},
            created_at=time.time(),
        ))
        return item_id

    async def get(self, scope_key: str, item_id: str) -> Item | None:
        for it in self._bucket(scope_key):
            if it.id == item_id:
                return it
        return None

    async def update(
        self,
        scope_key: str,
        item_id: str,
        content: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        bucket = self._bucket(scope_key)
        for i, it in enumerate(bucket):
            if it.id == item_id:
                bucket[i] = Item(
                    id=it.id,
                    scope_key=it.scope_key,
                    content=content if content is not None else it.content,
                    metadata=metadata if metadata is not None else it.metadata,
                    created_at=it.created_at,
                )
                return True
        return False

    async def delete(self, scope_key: str, item_id: str) -> bool:
        bucket = self._bucket(scope_key)
        for i, it in enumerate(bucket):
            if it.id == item_id:
                bucket.pop(i)
                return True
        return False

    async def list(
        self,
        scope_key: str,
        limit: int = 100,
        since_id: str | None = None,
    ) -> list[Item]:
        bucket = self._bucket(scope_key)
        if since_id is None:
            return bucket[:limit]
        start = 0
        for i, it in enumerate(bucket):
            if it.id == since_id:
                start = i + 1
                break
        return bucket[start:start + limit]

    async def search(
        self,
        scope_key: str,
        query: str,
        top_k: int = 5,
    ) -> list[Item]:
        # Simple keyword-overlap scoring — same algorithm as the original
        # EpisodicMemoryStore. Backends with real full-text override this.
        bucket = self._bucket(scope_key)
        if not query.strip():
            return bucket[-top_k:]
        q_words = set(query.lower().split())
        scored: list[tuple[Item, float]] = []
        for it in bucket:
            it_words = set(it.content.lower().split())
            overlap = len(q_words & it_words)
            if overlap > 0:
                scored.append((it, overlap / len(q_words)))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return [pair[0] for pair in scored[:top_k]]

    async def clear(self, scope_key: str) -> None:
        self._data.pop(scope_key, None)

    async def close(self) -> None:
        pass
