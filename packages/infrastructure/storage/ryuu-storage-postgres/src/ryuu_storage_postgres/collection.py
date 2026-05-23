"""PostgresCollectionStore — ICollectionStore on top of asyncpg.

Schema:
    CREATE TABLE <table> (
        id         TEXT PRIMARY KEY,
        scope_key  TEXT NOT NULL,
        content    TEXT NOT NULL,
        metadata   JSONB DEFAULT '{}',
        created_at DOUBLE PRECISION NOT NULL
    )
    CREATE INDEX <table>_scope_idx ON <table>(scope_key, created_at)

search() uses ILIKE for MVP. Add tsvector/pgvector column for production FTS/semantic.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from ryuu_storage_core import Item

from ryuu_storage_postgres._pool import get_pool


@dataclass
class PostgresCollectionStore:
    dsn: str
    table: str = "collection"
    _ready: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.table.replace("_", "").isalnum():
            raise ValueError(f"Invalid table name: {self.table!r}")

    async def _ensure_table(self) -> None:
        if self._ready:
            return
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            await conn.execute(
                f"CREATE TABLE IF NOT EXISTS {self.table} ("
                f"  id         TEXT PRIMARY KEY,"
                f"  scope_key  TEXT NOT NULL,"
                f"  content    TEXT NOT NULL,"
                f"  metadata   JSONB DEFAULT '{{}}',"
                f"  created_at DOUBLE PRECISION NOT NULL"
                f")"
            )
            await conn.execute(
                f"CREATE INDEX IF NOT EXISTS {self.table}_scope_idx"
                f" ON {self.table}(scope_key, created_at)"
            )
        self._ready = True

    def _row_to_item(self, row: Any) -> Item:
        meta = row["metadata"]
        if isinstance(meta, str):
            meta = json.loads(meta)
        return Item(
            id=row["id"],
            scope_key=row["scope_key"],
            content=row["content"],
            metadata=meta or {},
            created_at=row["created_at"],
        )

    async def append(
        self,
        scope_key: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        item_id = uuid.uuid4().hex
        ts = time.time()
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            await self._ensure_table()
            await conn.execute(
                f"INSERT INTO {self.table}(id, scope_key, content, metadata, created_at)"
                f" VALUES($1, $2, $3, $4, $5)",
                item_id, scope_key, content, json.dumps(metadata or {}), ts,
            )
        return item_id

    async def get(self, scope_key: str, item_id: str) -> Item | None:
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            await self._ensure_table()
            row = await conn.fetchrow(
                f"SELECT id, scope_key, content, metadata, created_at"
                f" FROM {self.table} WHERE scope_key = $1 AND id = $2",
                scope_key, item_id,
            )
            return self._row_to_item(row) if row else None

    async def update(
        self,
        scope_key: str,
        item_id: str,
        content: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        sets: list[str] = []
        params: list[Any] = []
        if content is not None:
            params.append(content)
            sets.append(f"content = ${len(params)}")
        if metadata is not None:
            params.append(json.dumps(metadata))
            sets.append(f"metadata = ${len(params)}")
        if not sets:
            return True
        params.extend([scope_key, item_id])
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            await self._ensure_table()
            result = await conn.execute(
                f"UPDATE {self.table} SET {', '.join(sets)}"
                f" WHERE scope_key = ${len(params) - 1} AND id = ${len(params)}",
                *params,
            )
            return result.split()[-1] != "0"

    async def delete(self, scope_key: str, item_id: str) -> bool:
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            await self._ensure_table()
            result = await conn.execute(
                f"DELETE FROM {self.table} WHERE scope_key = $1 AND id = $2",
                scope_key, item_id,
            )
            return result.split()[-1] != "0"

    async def list(
        self,
        scope_key: str,
        limit: int = 100,
        since_id: str | None = None,
    ) -> list[Item]:
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            await self._ensure_table()
            if since_id is None:
                rows = await conn.fetch(
                    f"SELECT id, scope_key, content, metadata, created_at"
                    f" FROM {self.table} WHERE scope_key = $1"
                    f" ORDER BY created_at ASC LIMIT $2",
                    scope_key, limit,
                )
            else:
                anchor = await conn.fetchrow(
                    f"SELECT created_at FROM {self.table}"
                    f" WHERE scope_key = $1 AND id = $2",
                    scope_key, since_id,
                )
                if anchor is None:
                    return []
                rows = await conn.fetch(
                    f"SELECT id, scope_key, content, metadata, created_at"
                    f" FROM {self.table} WHERE scope_key = $1 AND created_at > $2"
                    f" ORDER BY created_at ASC LIMIT $3",
                    scope_key, anchor["created_at"], limit,
                )
            return [self._row_to_item(r) for r in rows]

    async def search(
        self,
        scope_key: str,
        query: str,
        top_k: int = 5,
    ) -> list[Item]:
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            await self._ensure_table()
            if not query.strip():
                rows = await conn.fetch(
                    f"SELECT id, scope_key, content, metadata, created_at"
                    f" FROM {self.table} WHERE scope_key = $1"
                    f" ORDER BY created_at DESC LIMIT $2",
                    scope_key, top_k,
                )
            else:
                rows = await conn.fetch(
                    f"SELECT id, scope_key, content, metadata, created_at"
                    f" FROM {self.table} WHERE scope_key = $1 AND content ILIKE $2"
                    f" ORDER BY created_at DESC LIMIT $3",
                    scope_key, f"%{query}%", top_k,
                )
            return [self._row_to_item(r) for r in rows]

    async def clear(self, scope_key: str) -> None:
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            await self._ensure_table()
            await conn.execute(
                f"DELETE FROM {self.table} WHERE scope_key = $1", scope_key
            )

    async def close(self) -> None:
        pass  # pool lifecycle managed by _pool.close_all()
