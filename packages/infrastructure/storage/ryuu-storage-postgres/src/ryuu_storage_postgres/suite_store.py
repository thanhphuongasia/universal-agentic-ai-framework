"""PostgresSuiteStore — ISuiteStore over the migration's suites table.

When wired into the router, the eval app is DB-only for suites (no file-based
discovery / fallback). create_suite needs a domain to FK against; the seeder or
caller supplies one (or a configured default).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ryuu_storage_postgres._pool import get_pool


@dataclass
class PostgresSuiteStore:
    """Persistent ``ISuiteStore`` over the suites + test_cases tables."""

    dsn: str
    suites_table: str = "suites"
    cases_table: str = "test_cases"

    def __post_init__(self) -> None:
        for name in (self.suites_table, self.cases_table):
            if not name.replace("_", "").isalnum():
                raise ValueError(f"Invalid table name: {name!r}")

    async def list_suites(self) -> list[dict[str, Any]]:
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT s.id, s.name,"
                f"  (SELECT count(*) FROM {self.cases_table} t WHERE t.suite_id = s.id) AS case_count"
                f" FROM {self.suites_table} s ORDER BY s.id"
            )
        return [
            {"suite_id": r["id"], "title": r["name"], "case_count": r["case_count"]}
            for r in rows
        ]

    async def get_suite(self, suite_id: str) -> dict[str, Any] | None:
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT s.id, s.name, s.active_prompt_version_id,"
                f"  (SELECT count(*) FROM {self.cases_table} t WHERE t.suite_id = s.id) AS case_count"
                f" FROM {self.suites_table} s WHERE s.id = $1",
                suite_id,
            )
        if row is None:
            return None
        return {
            "suite_id": row["id"],
            "title": row["name"],
            "case_count": row["case_count"],
            "active_prompt_version_id": row["active_prompt_version_id"],
        }

    async def create_suite(
        self, suite_id: str, *, title: str = "", domain_id: str | None = None
    ) -> None:
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            await conn.execute(
                f"INSERT INTO {self.suites_table}(id, domain_id, name)"
                f" VALUES($1, $2, $3) ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name",
                suite_id, domain_id, title or suite_id,
            )

    async def delete_suite(self, suite_id: str) -> bool:
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            result = await conn.execute(
                f"DELETE FROM {self.suites_table} WHERE id = $1", suite_id
            )
            return result.split()[-1] != "0"
