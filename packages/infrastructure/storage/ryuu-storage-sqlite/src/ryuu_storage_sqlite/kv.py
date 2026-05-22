"""SqliteKVStore — IKVStore on top of a SQLite table.

Schema:
    CREATE TABLE <table> (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )

Many SqliteKVStore instances can share one DB file by passing different
`table` names. The underlying sqlite3 connection is shared via _connection.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ryuu_storage_sqlite._connection import get_connection, run


@dataclass
class SqliteKVStore:
    db_path: str | Path
    table: str = "kv"

    def __post_init__(self) -> None:
        # Quote the table name into the DDL — table names can't be parameterized
        # in sqlite, but we validate to keep this safe from injection.
        if not self.table.replace("_", "").isalnum():
            raise ValueError(f"Invalid table name: {self.table!r}")
        conn = get_connection(self.db_path)
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {self.table} "
            f"(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )

    def _conn(self):
        return get_connection(self.db_path)

    async def get(self, key: str) -> str | None:
        def _do() -> str | None:
            row = self._conn().execute(
                f"SELECT value FROM {self.table} WHERE key = ?", (key,)
            ).fetchone()
            return row[0] if row else None
        return await run(_do)

    async def put(self, key: str, value: str) -> None:
        def _do() -> None:
            self._conn().execute(
                f"INSERT INTO {self.table}(key, value) VALUES(?, ?) "
                f"ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
        await run(_do)

    async def delete(self, key: str) -> bool:
        def _do() -> bool:
            cur = self._conn().execute(
                f"DELETE FROM {self.table} WHERE key = ?", (key,)
            )
            return cur.rowcount > 0
        return await run(_do)

    async def keys(self, prefix: str = "") -> Iterable[str]:
        def _do() -> list[str]:
            if prefix:
                rows = self._conn().execute(
                    f"SELECT key FROM {self.table} WHERE key LIKE ? || '%' "
                    f"ORDER BY key",
                    (prefix,),
                ).fetchall()
            else:
                rows = self._conn().execute(
                    f"SELECT key FROM {self.table} ORDER BY key"
                ).fetchall()
            return [r[0] for r in rows]
        return await run(_do)

    async def close(self) -> None:
        # Connection is shared via the module-level cache — don't close here.
        pass
