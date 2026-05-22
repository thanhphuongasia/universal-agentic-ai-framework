"""InMemoryKVStore — dict-backed IKVStore for tests and dev."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass
class InMemoryKVStore:
    """Plain dict. Wipes on process restart. Thread-safe? No — single-task only."""
    table: str = "default"
    _data: dict[str, str] = field(default_factory=dict)

    async def get(self, key: str) -> str | None:
        return self._data.get(key)

    async def put(self, key: str, value: str) -> None:
        self._data[key] = value

    async def delete(self, key: str) -> bool:
        return self._data.pop(key, None) is not None

    async def keys(self, prefix: str = "") -> Iterable[str]:
        if not prefix:
            return list(self._data.keys())
        return [k for k in self._data.keys() if k.startswith(prefix)]

    async def close(self) -> None:
        # Nothing to release.
        pass
