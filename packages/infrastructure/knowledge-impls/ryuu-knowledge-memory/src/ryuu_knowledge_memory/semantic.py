"""SemanticMemoryStore — long-term consolidated knowledge written by DreamingConsolidator.

Entries here are distilled facts promoted from episodic memory. They never
expire automatically; only explicit deletion or `update()` removes them.

Two retrieval modes:
  • Embedding-based (when entry.embedding is set): cosine similarity
  • Keyword-overlap fallback (same as EpisodicMemoryStore)
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field
from typing import Any

from ryuu_knowledge_memory.store import MemoryEntry, MemoryLayer


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


@dataclass
class SemanticMemoryStore:
    layer = MemoryLayer.SEMANTIC
    # dict[scope_key, dict[entry_id, MemoryEntry]]
    _store: dict[str, dict[str, MemoryEntry]] = field(default_factory=dict)

    async def store(
        self,
        content: str,
        scope_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        bucket = self._store.setdefault(scope_key, {})
        meta = metadata or {}
        entry = MemoryEntry(
            content=content,
            metadata=meta,
            importance=meta.get("importance", "high"),
            embedding=meta.get("embedding"),
        )
        bucket[entry.id] = entry

    async def retrieve(
        self,
        query: str,
        scope_key: str,
        top_k: int = 5,
        query_embedding: list[float] | None = None,
    ) -> list[MemoryEntry]:
        bucket = self._store.get(scope_key, {})
        entries = list(bucket.values())
        if not entries:
            return []

        # Embedding path
        if query_embedding:
            scored = []
            for e in entries:
                if e.embedding:
                    sim = _cosine(query_embedding, e.embedding)
                    scored.append(dataclasses.replace(e, score=sim))
                else:
                    scored.append(dataclasses.replace(e, score=0.0))
            scored.sort(key=lambda e: e.score, reverse=True)
            return scored[:top_k]

        # Keyword fallback
        if not query.strip():
            return entries[:top_k]
        query_words = set(query.lower().split())
        scored = []
        for e in entries:
            overlap = len(query_words & set(e.content.lower().split()))
            if overlap > 0:
                scored.append(dataclasses.replace(e, score=overlap / len(query_words)))
        scored.sort(key=lambda e: e.score, reverse=True)
        return scored[:top_k]

    async def update(self, entry_id: str, new_content: str) -> None:
        """Replace content of an existing entry (used when conflict resolved)."""
        for bucket in self._store.values():
            if entry_id in bucket:
                bucket[entry_id] = dataclasses.replace(bucket[entry_id], content=new_content)
                return

    async def clear(self, scope_key: str) -> None:
        self._store.pop(scope_key, None)
