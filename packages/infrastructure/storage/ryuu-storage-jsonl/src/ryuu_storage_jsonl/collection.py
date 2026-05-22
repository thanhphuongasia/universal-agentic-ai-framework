"""JsonlCollectionStore — append-only JSONL files, one file per scope.

Layout:
    <root>/<table>/<scope_key>.jsonl

Each line is one JSON-encoded Item:
    {"id": "...", "content": "...", "metadata": {...}, "created_at": ...}

Why "one file per scope":
  - Append is atomic at the OS layer (no cross-scope contention)
  - GDPR delete = `rm <scope>.jsonl` — instant + complete
  - Easy debug: `tail -f` one specific user's stream
  - Concurrent writers across scopes don't lock each other
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ryuu_storage_core import Item

# Conservative scope_key sanitization: keep letters/digits/dot/underscore/dash,
# replace anything else with "_". Prevents directory traversal and OS-specific
# bad chars (`:` on Windows, `/` everywhere). Original scope_key is preserved
# inside the JSON payload — only the FILENAME is sanitized.
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]")


def _safe_name(scope_key: str) -> str:
    name = _SAFE_FILENAME.sub("_", scope_key)
    return name or "_"


@dataclass
class JsonlCollectionStore:
    """File-per-scope append-only JSONL store.

    Concurrent appends to the SAME scope from one process: serialized by the
    asyncio lock. Concurrent appends to DIFFERENT scopes: free (different files).
    Cross-process concurrency to same scope: relies on POSIX O_APPEND atomicity
    for writes ≤ PIPE_BUF; for larger writes you want SQLite.
    """
    root_dir: str | Path
    table: str = "default"
    _locks: dict[str, asyncio.Lock] | None = None

    def __post_init__(self) -> None:
        if not self.table.replace("_", "").replace("-", "").isalnum():
            raise ValueError(f"Invalid table name: {self.table!r}")
        self.root_dir = Path(self.root_dir).expanduser()
        self._table_dir().mkdir(parents=True, exist_ok=True)
        self._locks = {}

    def _table_dir(self) -> Path:
        return Path(self.root_dir) / self.table

    def _file(self, scope_key: str) -> Path:
        return self._table_dir() / f"{_safe_name(scope_key)}.jsonl"

    def _lock(self, scope_key: str) -> asyncio.Lock:
        # asyncio.Lock is task-safe within one event loop
        assert self._locks is not None
        lock = self._locks.get(scope_key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[scope_key] = lock
        return lock

    # ------------------------------------------------------------------ #
    # ICollectionStore impl
    # ------------------------------------------------------------------ #
    async def append(
        self,
        scope_key: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        item_id = uuid.uuid4().hex
        record = {
            "id": item_id,
            "scope_key": scope_key,  # preserved here even if filename is sanitized
            "content": content,
            "metadata": metadata or {},
            "created_at": time.time(),
        }
        line = json.dumps(record, ensure_ascii=False) + "\n"
        path = self._file(scope_key)

        async with self._lock(scope_key):
            await asyncio.to_thread(self._append_sync, path, line)
        return item_id

    @staticmethod
    def _append_sync(path: Path, line: str) -> None:
        # Single open()-write()-close() per append. The append is atomic at the
        # OS layer for write sizes ≤ PIPE_BUF (typically 4 KB on Linux/macOS).
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)

    async def _read_all(self, scope_key: str) -> list[Item]:
        path = self._file(scope_key)
        if not path.exists():
            return []

        def _do() -> list[Item]:
            items: list[Item] = []
            with open(path, encoding="utf-8") as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        rec = json.loads(raw)
                    except json.JSONDecodeError:
                        # Corrupt line — skip, don't fail the whole file
                        continue
                    items.append(Item(
                        id=rec.get("id", ""),
                        scope_key=rec.get("scope_key", scope_key),
                        content=rec.get("content", ""),
                        metadata=rec.get("metadata", {}) or {},
                        created_at=float(rec.get("created_at", 0.0)),
                    ))
            return items
        return await asyncio.to_thread(_do)

    async def get(self, scope_key: str, item_id: str) -> Item | None:
        for it in await self._read_all(scope_key):
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
        # Append-only semantics: "update" rewrites the whole file. This is
        # discouraged on JSONL — use SQLite for frequently-mutated data.
        async with self._lock(scope_key):
            items = await self._read_all(scope_key)
            found = False
            for i, it in enumerate(items):
                if it.id == item_id:
                    items[i] = Item(
                        id=it.id,
                        scope_key=it.scope_key,
                        content=content if content is not None else it.content,
                        metadata=metadata if metadata is not None else it.metadata,
                        created_at=it.created_at,
                    )
                    found = True
                    break
            if not found:
                return False

            def _rewrite() -> None:
                path = self._file(scope_key)
                tmp = path.with_suffix(".jsonl.tmp")
                with open(tmp, "w", encoding="utf-8") as f:
                    for it in items:
                        f.write(json.dumps({
                            "id": it.id,
                            "scope_key": it.scope_key,
                            "content": it.content,
                            "metadata": it.metadata,
                            "created_at": it.created_at,
                        }, ensure_ascii=False) + "\n")
                tmp.replace(path)
            await asyncio.to_thread(_rewrite)
        return True

    async def delete(self, scope_key: str, item_id: str) -> bool:
        async with self._lock(scope_key):
            items = await self._read_all(scope_key)
            new_items = [it for it in items if it.id != item_id]
            if len(new_items) == len(items):
                return False

            def _rewrite() -> None:
                path = self._file(scope_key)
                tmp = path.with_suffix(".jsonl.tmp")
                with open(tmp, "w", encoding="utf-8") as f:
                    for it in new_items:
                        f.write(json.dumps({
                            "id": it.id,
                            "scope_key": it.scope_key,
                            "content": it.content,
                            "metadata": it.metadata,
                            "created_at": it.created_at,
                        }, ensure_ascii=False) + "\n")
                tmp.replace(path)
            await asyncio.to_thread(_rewrite)
        return True

    async def list(
        self,
        scope_key: str,
        limit: int = 100,
        since_id: str | None = None,
    ) -> list[Item]:
        items = await self._read_all(scope_key)
        if since_id is None:
            return items[:limit]
        start = 0
        for i, it in enumerate(items):
            if it.id == since_id:
                start = i + 1
                break
        return items[start:start + limit]

    async def search(
        self,
        scope_key: str,
        query: str,
        top_k: int = 5,
    ) -> list[Item]:
        items = await self._read_all(scope_key)
        if not query.strip():
            return items[-top_k:]

        # Keyword-overlap scoring — same algorithm as in-memory EpisodicMemory
        q_words = set(query.lower().split())
        scored: list[tuple[Item, float]] = []
        for it in items:
            it_words = set(it.content.lower().split())
            overlap = len(q_words & it_words)
            if overlap > 0:
                scored.append((it, overlap / len(q_words)))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return [pair[0] for pair in scored[:top_k]]

    async def clear(self, scope_key: str) -> None:
        async with self._lock(scope_key):
            path = self._file(scope_key)
            if path.exists():
                await asyncio.to_thread(path.unlink)

    async def close(self) -> None:
        # Nothing to release — each append opens-writes-closes its own handle.
        pass
