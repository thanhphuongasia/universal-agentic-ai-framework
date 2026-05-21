from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class MemoryLayer(StrEnum):
    WORKING = "working"
    EPISODIC = "episodic"


@dataclass(frozen=True)
class MemoryEntry:
    content: str
    score: float = 1.0
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


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
