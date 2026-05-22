"""SqliteCollectionStore — ICollectionStore on top of a SQLite table.

Schema:
    CREATE TABLE <table> (
        id          TEXT PRIMARY KEY,
        scope_key   TEXT NOT NULL,
        content     TEXT NOT NULL,
        metadata    TEXT NOT NULL,    -- JSON-encoded dict
        created_at  REAL NOT NULL
    )
    CREATE INDEX <table>_scope ON <table>(scope_key, created_at)
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ryuu_storage_core import Item

from ryuu_storage_sqlite._connection import get_connection, run


@dataclass
class SqliteCollectionStore:
    db_path: str | Path
    table: str = "collection"

    def __post_init__(self) -> None:
        if not self.table.replace("_", "").isalnum():
            raise ValueError(f"Invalid table name: {self.table!r}")
        conn = get_connection(self.db_path)
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {self.table} ("
            f"  id         TEXT PRIMARY KEY,"
            f"  scope_key  TEXT NOT NULL,"
            f"  content    TEXT NOT NULL,"
            f"  metadata   TEXT NOT NULL,"
            f"  created_at REAL NOT NULL"
            f")"
        )
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS {self.table}_scope_idx "
            f"ON {self.table}(scope_key, created_at)"
        )

    def _conn(self):
        return get_connection(self.db_path)

    def _row_to_item(self, row: tuple) -> Item:
        item_id, scope_key, content, metadata_json, created_at = row
        return Item(
            id=item_id,
            scope_key=scope_key,
            content=content,
            metadata=json.loads(metadata_json) if metadata_json else {},
            created_at=created_at,
        )

    async def append(
        self,
        scope_key: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        item_id = uuid.uuid4().hex
        ts = time.time()

        def _do() -> None:
            self._conn().execute(
                f"INSERT INTO {self.table}(id, scope_key, content, metadata, created_at) "
                f"VALUES(?, ?, ?, ?, ?)",
                (item_id, scope_key, content, json.dumps(metadata or {}), ts),
            )
        await run(_do)
        return item_id

    async def get(self, scope_key: str, item_id: str) -> Item | None:
        def _do() -> Item | None:
            row = self._conn().execute(
                f"SELECT id, scope_key, content, metadata, created_at FROM {self.table} "
                f"WHERE scope_key = ? AND id = ?",
                (scope_key, item_id),
            ).fetchone()
            return self._row_to_item(row) if row else None
        return await run(_do)

    async def update(
        self,
        scope_key: str,
        item_id: str,
        content: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        def _do() -> bool:
            sets: list[str] = []
            params: list[Any] = []
            if content is not None:
                sets.append("content = ?")
                params.append(content)
            if metadata is not None:
                sets.append("metadata = ?")
                params.append(json.dumps(metadata))
            if not sets:
                return True   # no-op
            params.extend([scope_key, item_id])
            cur = self._conn().execute(
                f"UPDATE {self.table} SET {', '.join(sets)} "
                f"WHERE scope_key = ? AND id = ?",
                params,
            )
            return cur.rowcount > 0
        return await run(_do)

    async def delete(self, scope_key: str, item_id: str) -> bool:
        def _do() -> bool:
            cur = self._conn().execute(
                f"DELETE FROM {self.table} WHERE scope_key = ? AND id = ?",
                (scope_key, item_id),
            )
            return cur.rowcount > 0
        return await run(_do)

    async def list(
        self,
        scope_key: str,
        limit: int = 100,
        since_id: str | None = None,
    ) -> list[Item]:
        def _do() -> list[Item]:
            if since_id is None:
                rows = self._conn().execute(
                    f"SELECT id, scope_key, content, metadata, created_at FROM {self.table} "
                    f"WHERE scope_key = ? ORDER BY created_at ASC LIMIT ?",
                    (scope_key, limit),
                ).fetchall()
            else:
                # Get since_id's created_at to use as cursor
                anchor = self._conn().execute(
                    f"SELECT created_at FROM {self.table} WHERE scope_key = ? AND id = ?",
                    (scope_key, since_id),
                ).fetchone()
                if anchor is None:
                    return []
                rows = self._conn().execute(
                    f"SELECT id, scope_key, content, metadata, created_at FROM {self.table} "
                    f"WHERE scope_key = ? AND created_at > ? "
                    f"ORDER BY created_at ASC LIMIT ?",
                    (scope_key, anchor[0], limit),
                ).fetchall()
            return [self._row_to_item(r) for r in rows]
        return await run(_do)

    async def search(
        self,
        scope_key: str,
        query: str,
        top_k: int = 5,
    ) -> list[Item]:
        # Naive LIKE-based search for MVP. Real FTS5 backed search is a
        # follow-up: enable FTS5 virtual table + INSERT INTO trigger.
        def _do() -> list[Item]:
            if not query.strip():
                rows = self._conn().execute(
                    f"SELECT id, scope_key, content, metadata, created_at FROM {self.table} "
                    f"WHERE scope_key = ? ORDER BY created_at DESC LIMIT ?",
                    (scope_key, top_k),
                ).fetchall()
                return [self._row_to_item(r) for r in rows]
            pattern = f"%{query}%"
            rows = self._conn().execute(
                f"SELECT id, scope_key, content, metadata, created_at FROM {self.table} "
                f"WHERE scope_key = ? AND content LIKE ? "
                f"ORDER BY created_at DESC LIMIT ?",
                (scope_key, pattern, top_k),
            ).fetchall()
            return [self._row_to_item(r) for r in rows]
        return await run(_do)

    async def clear(self, scope_key: str) -> None:
        def _do() -> None:
            self._conn().execute(
                f"DELETE FROM {self.table} WHERE scope_key = ?", (scope_key,)
            )
        await run(_do)

    async def close(self) -> None:
        pass
