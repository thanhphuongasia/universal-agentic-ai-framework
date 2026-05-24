"""PostgresProfileStore — temporal user profile facts.

Schema:
    user_profile: one row per (scope_key, key, version). Active row has valid_to IS NULL.
    A partial unique index enforces at most one active row per (scope_key, key).

Pattern — setting a new value never overwrites history:
    1. UPDATE ... SET valid_to = now() WHERE valid_to IS NULL   ← close old active row
    2. INSERT new row with valid_to = NULL                       ← open new active row

This means the full evolution of every fact is preserved and queryable:
    Goal in 2024: "Learn AI frameworks"
    Goal in 2025: "Ship UAAF to production"

Point-in-time query: WHERE valid_from <= $ts AND (valid_to IS NULL OR valid_to > $ts)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from ryuu_storage_core import ProfileEntry  # noqa: F401 — re-exported for convenience

from ryuu_storage_postgres._pool import get_pool


@dataclass
class PostgresProfileStore:
    dsn: str
    table: str = "user_profile"
    _ready: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.table.replace("_", "").isalnum():
            raise ValueError(f"Invalid table name: {self.table!r}")

    async def _ensure_table(self) -> None:
        if self._ready:
            return
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.table} (
                    id         BIGSERIAL PRIMARY KEY,
                    scope_key  TEXT NOT NULL,
                    key        TEXT NOT NULL,
                    value      TEXT NOT NULL,
                    source     TEXT NOT NULL DEFAULT 'user',
                    valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
                    valid_to   TIMESTAMPTZ,
                    note       TEXT
                )
            """)
            # Only one active (valid_to IS NULL) row per (scope_key, key)
            await conn.execute(
                f"CREATE UNIQUE INDEX IF NOT EXISTS {self.table}_one_active"
                f" ON {self.table}(scope_key, key)"
                f" WHERE valid_to IS NULL"
            )
            await conn.execute(
                f"CREATE INDEX IF NOT EXISTS {self.table}_history"
                f" ON {self.table}(scope_key, key, valid_from DESC)"
            )
        self._ready = True

    async def set_value(
        self,
        scope_key: str,
        key: str,
        value: str,
        *,
        source: str = "user",
        note: str | None = None,
    ) -> None:
        """Set a profile fact. Closes the current active row; inserts a new one.

        Idempotent for the same value — if value is unchanged the old row is
        closed and a new identical one is opened (history is recorded anyway).
        """
        await self._ensure_table()
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    f"UPDATE {self.table} SET valid_to = now()"
                    f" WHERE scope_key = $1 AND key = $2 AND valid_to IS NULL",
                    scope_key, key,
                )
                await conn.execute(
                    f"INSERT INTO {self.table}(scope_key, key, value, source, note)"
                    f" VALUES($1, $2, $3, $4, $5)",
                    scope_key, key, value, source, note,
                )

    async def get_current(self, scope_key: str) -> dict[str, str]:
        """Return all active key→value pairs for a scope."""
        await self._ensure_table()
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT key, value FROM {self.table}"
                f" WHERE scope_key = $1 AND valid_to IS NULL"
                f" ORDER BY key",
                scope_key,
            )
            return {r["key"]: r["value"] for r in rows}

    async def get_at(self, scope_key: str, at: datetime) -> dict[str, str]:
        """Return the profile as it was at a specific point in time."""
        await self._ensure_table()
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT key, value FROM {self.table}"
                f" WHERE scope_key = $1"
                f"   AND valid_from <= $2"
                f"   AND (valid_to IS NULL OR valid_to > $2)"
                f" ORDER BY key",
                scope_key, at,
            )
            return {r["key"]: r["value"] for r in rows}

    async def get_history(self, scope_key: str, key: str) -> list[ProfileEntry]:
        """Full change history for one key, newest first."""
        await self._ensure_table()
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT key, value, source, valid_from, valid_to, note"
                f" FROM {self.table}"
                f" WHERE scope_key = $1 AND key = $2"
                f" ORDER BY valid_from DESC",
                scope_key, key,
            )
            return [
                ProfileEntry(
                    key=r["key"],
                    value=r["value"],
                    source=r["source"],
                    valid_from=r["valid_from"],
                    valid_to=r["valid_to"],
                    note=r["note"],
                )
                for r in rows
            ]

    async def all_keys(self, scope_key: str) -> Iterable[str]:
        """Return all keys that have ever been set for a scope (including expired)."""
        await self._ensure_table()
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT DISTINCT key FROM {self.table}"
                f" WHERE scope_key = $1 ORDER BY key",
                scope_key,
            )
            return [r["key"] for r in rows]

    async def as_prompt_block(self, scope_key: str) -> str:
        """Format current active profile for injection into the system prompt.

        Returns empty string if no profile entries exist yet.
        """
        current = await self.get_current(scope_key)
        if not current:
            return ""
        lines = "\n".join(f"  • {k}: {v}" for k, v in sorted(current.items()))
        return f"User profile:\n{lines}"

    async def delete_key(self, scope_key: str, key: str) -> None:
        """Hard-delete all history for one key (GDPR / explicit user request)."""
        await self._ensure_table()
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            await conn.execute(
                f"DELETE FROM {self.table} WHERE scope_key = $1 AND key = $2",
                scope_key, key,
            )

    async def delete_scope(self, scope_key: str) -> None:
        """Hard-delete entire profile for a scope."""
        await self._ensure_table()
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            await conn.execute(
                f"DELETE FROM {self.table} WHERE scope_key = $1", scope_key
            )
