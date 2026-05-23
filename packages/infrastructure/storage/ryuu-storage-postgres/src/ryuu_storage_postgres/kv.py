"""PostgresKVStore — IKVStore on top of asyncpg.

Schema:
    CREATE TABLE <table> (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from ryuu_storage_postgres._pool import get_pool


@dataclass
class PostgresKVStore:
    dsn: str
    table: str = "kv"
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
                f"  key   TEXT PRIMARY KEY,"
                f"  value TEXT NOT NULL"
                f")"
            )
        self._ready = True

    async def get(self, key: str) -> str | None:
        await self._ensure_table()
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT value FROM {self.table} WHERE key = $1", key
            )
            return row["value"] if row else None

    async def put(self, key: str, value: str) -> None:
        await self._ensure_table()
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            await conn.execute(
                f"INSERT INTO {self.table}(key, value) VALUES($1, $2)"
                f" ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                key, value,
            )

    async def delete(self, key: str) -> bool:
        await self._ensure_table()
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            result = await conn.execute(
                f"DELETE FROM {self.table} WHERE key = $1", key
            )
            return result.split()[-1] != "0"

    async def keys(self, prefix: str = "") -> Iterable[str]:
        await self._ensure_table()
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            if prefix:
                rows = await conn.fetch(
                    f"SELECT key FROM {self.table} WHERE key LIKE $1 ORDER BY key",
                    f"{prefix}%",
                )
            else:
                rows = await conn.fetch(
                    f"SELECT key FROM {self.table} ORDER BY key"
                )
            return [r["key"] for r in rows]

    async def close(self) -> None:
        pass  # pool lifecycle managed by _pool.close_all()
