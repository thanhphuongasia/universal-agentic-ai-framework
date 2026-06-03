from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4


class MemoryLayer(StrEnum):
    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"


@dataclass(frozen=True)
class MemoryEntry:
    content: str
    score: float = 1.0
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
    # Quality-layer fields — all optional, backward-compat
    id: str = field(default_factory=lambda: uuid4().hex)
    importance: str = "medium"          # "high" | "medium" | "low"
    status: str = "active"              # "active" | "consolidated" | "archived"
    access_count: int = 0
    was_corrected: bool = False
    superseded_by: str | None = None
    consolidated_at: float | None = None
    archived_until: float | None = None  # Unix ts; None = not archived
    embedding: list[float] | None = None


@runtime_checkable
class IMemoryStore(Protocol):
    layer: MemoryLayer

    async def store(
        self,
        content: str,
        scope_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> None: ...

    async def retrieve(
        self,
        query: str,
        scope_key: str,
        top_k: int = 5,
    ) -> list[MemoryEntry]: ...

    async def clear(self, scope_key: str) -> None: ...
