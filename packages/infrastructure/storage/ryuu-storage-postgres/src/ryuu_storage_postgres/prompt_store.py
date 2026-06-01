"""PostgresPromptStore — IPromptStore on top of asyncpg, bound to the eval schema.

Persistent backend for the prompt lifecycle (versioning + promotion) defined by
``ryuu_prompts.IPromptStore``. The in-memory store is the volatile reference impl;
this one survives restarts.

Schema ownership: the eval schema (docs/eval-prompt-store-schema.sql) is the single
source of truth for DDL. This store does **not** create tables — run the migration
first. It reads/writes two of those tables:

    prompt_versions              — one row per (suite_id, version); config is JSONB
    suites.active_prompt_version_id  — THE active pointer (which version is live)

The active pointer lives on ``suites`` (not a side table), matching the migration.
Because ``prompt_versions.suite_id`` has an FK to ``suites``, a suite row must exist
before saving versions — use ``ensure_suite()`` (the parent system/domain rows are
the seeder's responsibility).

``config`` round-trips through ``PromptConfig.to_dict()/from_dict()``. ``status``
matches the SQL CHECK; ``'production'`` is never a status — live-ness is the pointer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from ryuu_prompts import (
    PromptConfig,
    PromptStatus,
    PromptStoreError,
    PromptVersion,
    PromptVersionNotFoundError,
)

from ryuu_storage_postgres._pool import get_pool


def _to_dt(epoch: float | None) -> datetime | None:
    """Float epoch → aware datetime (asyncpg writes TIMESTAMPTZ). None passes through."""
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


def _to_epoch(dt: datetime | None) -> float | None:
    """asyncpg TIMESTAMPTZ (datetime) → float epoch. None passes through."""
    return dt.timestamp() if dt is not None else None


@dataclass
class PostgresPromptStore:
    """Persistent ``IPromptStore`` over the migration's prompt_versions + suites."""

    dsn: str
    versions_table: str = "prompt_versions"
    suites_table: str = "suites"

    def __post_init__(self) -> None:
        for name in (self.versions_table, self.suites_table):
            if not name.replace("_", "").isalnum():
                raise ValueError(f"Invalid table name: {name!r}")

    # ------------------------------------------------------------------
    # Row → PromptVersion
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_version(row) -> PromptVersion:
        config_raw = row["config"]
        if isinstance(config_raw, str):
            config_raw = json.loads(config_raw)
        return PromptVersion(
            id=row["id"],
            suite_id=row["suite_id"],
            version=row["version"],
            config=PromptConfig.from_dict(config_raw),
            status=PromptStatus(row["status"]),
            promoted_at=_to_epoch(row["promoted_at"]),
            promoted_by=row["promoted_by"],
            created_at=_to_epoch(row["created_at"]) or 0.0,
        )

    # ------------------------------------------------------------------
    # Suite helper — FK requires a suites row before saving versions
    # ------------------------------------------------------------------

    async def ensure_suite(self, suite_id: str, *, domain_id: str, name: str = "") -> None:
        """Insert a suites row if absent (no-op if it already exists).

        The parent ``domains``/``systems`` rows must already exist (FK). Creating
        those is the seeder's job — this only guarantees the suite the prompt
        versions attach to.
        """
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            await conn.execute(
                f"INSERT INTO {self.suites_table}(id, domain_id, name)"
                f" VALUES($1, $2, $3) ON CONFLICT (id) DO NOTHING",
                suite_id, domain_id, name or suite_id,
            )

    # ------------------------------------------------------------------
    # IPromptStore
    # ------------------------------------------------------------------

    async def save(self, version: PromptVersion) -> None:
        config_json = json.dumps(version.config.to_dict(), ensure_ascii=False)
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            await conn.execute(
                f"INSERT INTO {self.versions_table}"
                f" (id, suite_id, version, config, status, promoted_at, promoted_by, created_at)"
                f" VALUES($1, $2, $3, $4::jsonb, $5, $6, $7, COALESCE($8::timestamptz, now()))"
                f" ON CONFLICT (suite_id, version) DO UPDATE SET"
                f"   id          = EXCLUDED.id,"
                f"   config      = EXCLUDED.config,"
                f"   status      = EXCLUDED.status,"
                f"   promoted_at = EXCLUDED.promoted_at,"
                f"   promoted_by = EXCLUDED.promoted_by",
                version.id, version.suite_id, version.version, config_json,
                version.status.value, _to_dt(version.promoted_at), version.promoted_by,
                _to_dt(version.created_at) if version.created_at else None,
            )

    async def get(self, suite_id: str, version: str) -> PromptVersion | None:
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT * FROM {self.versions_table}"
                f" WHERE suite_id = $1 AND version = $2",
                suite_id, version,
            )
            return self._row_to_version(row) if row else None

    async def list_versions(self, suite_id: str) -> list[PromptVersion]:
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM {self.versions_table}"
                f" WHERE suite_id = $1 ORDER BY created_at ASC, version ASC",
                suite_id,
            )
            return [self._row_to_version(r) for r in rows]

    async def set_status(
        self, suite_id: str, version: str, status: PromptStatus
    ) -> PromptVersion:
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"UPDATE {self.versions_table} SET status = $3"
                f" WHERE suite_id = $1 AND version = $2 RETURNING *",
                suite_id, version, status.value,
            )
            if row is None:
                raise PromptVersionNotFoundError(f"{suite_id}/{version} not found")
            return self._row_to_version(row)

    async def promote(self, suite_id: str, version: str, *, by: str) -> PromptVersion:
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            async with conn.transaction():
                current = await conn.fetchrow(
                    f"SELECT id, status FROM {self.versions_table}"
                    f" WHERE suite_id = $1 AND version = $2",
                    suite_id, version,
                )
                if current is None:
                    raise PromptVersionNotFoundError(f"{suite_id}/{version} not found")
                if current["status"] == PromptStatus.ARCHIVED.value:
                    raise PromptStoreError(
                        f"cannot promote archived version {suite_id}/{version}"
                    )
                row = await conn.fetchrow(
                    f"UPDATE {self.versions_table}"
                    f" SET promoted_at = now(), promoted_by = $3"
                    f" WHERE suite_id = $1 AND version = $2 RETURNING *",
                    suite_id, version, by,
                )
                # The active pointer lives on suites — single source of truth.
                await conn.execute(
                    f"UPDATE {self.suites_table}"
                    f" SET active_prompt_version_id = $2 WHERE id = $1",
                    suite_id, current["id"],
                )
            return self._row_to_version(row)

    async def get_active(self, suite_id: str) -> PromptVersion | None:
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT v.* FROM {self.suites_table} s"
                f" JOIN {self.versions_table} v ON v.id = s.active_prompt_version_id"
                f" WHERE s.id = $1",
                suite_id,
            )
            return self._row_to_version(row) if row else None

    async def close(self) -> None:
        pass  # pool lifecycle managed by _pool.close_all()
