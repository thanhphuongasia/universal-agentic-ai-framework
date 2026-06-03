"""EpisodicMemoryStore — long-term observations + keyword-overlap retrieval.

Same two-backend pattern as WorkingMemoryStore.

Internal storage uses dict[entry_id, MemoryEntry] (insertion-ordered) so that
lifecycle methods (mark_consolidated, archive, eviction) can look up and replace
entries by ID without linear scans.
"""

from __future__ import annotations

import dataclasses
import time
from dataclasses import dataclass, field
from typing import Any

from ryuu_storage_core import ICollectionStore

from ryuu_knowledge_memory.store import MemoryEntry, MemoryLayer


@dataclass
class EpisodicMemoryStore:
    layer = MemoryLayer.EPISODIC
    max_entries: int = 500
    collection: ICollectionStore | None = None
    # dict[scope_key, dict[entry_id, MemoryEntry]] — insertion-ordered
    _store: dict[str, dict[str, MemoryEntry]] = field(default_factory=dict)

    # ── Core IMemoryStore interface ──────────────────────────────────────────

    async def store(
        self,
        content: str,
        scope_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if self.collection is not None:
            await self.collection.append(scope_key, content, metadata or {})
            return
        bucket = self._store.setdefault(scope_key, {})
        if len(bucket) >= self.max_entries:
            oldest_id = next(iter(bucket))
            del bucket[oldest_id]
        entry = MemoryEntry(
            content=content,
            metadata=metadata or {},
            importance=(metadata or {}).get("importance", "medium"),
        )
        bucket[entry.id] = entry

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

        bucket = self._store.get(scope_key, {})
        active = [e for e in bucket.values() if e.status == "active"]

        if not query.strip():
            return active[-top_k:]

        query_words = set(query.lower().split())
        scored: list[MemoryEntry] = []
        for entry in active:
            entry_words = set(entry.content.lower().split())
            overlap = len(query_words & entry_words)
            if overlap > 0:
                score = overlap / len(query_words)
                scored.append(dataclasses.replace(entry, score=score))

        scored.sort(key=lambda e: e.score, reverse=True)
        return scored[:top_k]

    async def clear(self, scope_key: str) -> None:
        if self.collection is not None:
            await self.collection.clear(scope_key)
            return
        self._store.pop(scope_key, None)

    # ── Lifecycle methods (in-memory only; collection backend: subclass) ─────

    async def get_unconsolidated(
        self, scope_key: str, limit: int = 50
    ) -> list[MemoryEntry]:
        """Active entries that have never been consolidated into semantic."""
        bucket = self._store.get(scope_key, {})
        pending = [
            e for e in bucket.values()
            if e.status == "active" and e.consolidated_at is None
        ]
        return pending[:limit]

    async def get_all_active(self, scope_key: str) -> list[MemoryEntry]:
        """Return active + consolidated entries (excludes archived/deleted).
        EvictionJob needs consolidated entries to decide if they're deletable.
        """
        bucket = self._store.get(scope_key, {})
        return [e for e in bucket.values() if e.status in ("active", "consolidated")]

    async def mark_consolidated(self, entry_ids: list[str]) -> None:
        """Mark entries as consolidated (episodic → semantic promotion done)."""
        now = time.time()
        for scope_bucket in self._store.values():
            for eid in entry_ids:
                if eid in scope_bucket:
                    scope_bucket[eid] = dataclasses.replace(
                        scope_bucket[eid],
                        status="consolidated",
                        consolidated_at=now,
                    )

    async def archive(self, entry_id: str, ttl_days: int = 30) -> None:
        """Move an entry to archived state with a TTL."""
        ttl_seconds = ttl_days * 86_400
        until = time.time() + ttl_seconds
        for scope_bucket in self._store.values():
            if entry_id in scope_bucket:
                scope_bucket[entry_id] = dataclasses.replace(
                    scope_bucket[entry_id],
                    status="archived",
                    archived_until=until,
                )
                return

    async def delete_expired_archives(self, scope_key: str) -> None:
        """Hard-delete archived entries whose TTL has elapsed."""
        now = time.time()
        bucket = self._store.get(scope_key, {})
        expired = [
            eid for eid, e in bucket.items()
            if e.status == "archived" and e.archived_until is not None and e.archived_until <= now
        ]
        for eid in expired:
            del bucket[eid]

    async def delete(self, entry_id: str) -> None:
        """Hard-delete a single entry by ID."""
        for scope_bucket in self._store.values():
            if entry_id in scope_bucket:
                del scope_bucket[entry_id]
                return
