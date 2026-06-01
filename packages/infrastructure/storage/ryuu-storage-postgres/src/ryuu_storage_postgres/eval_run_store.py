"""PostgresEvalRunStore — IEvalRunStore over eval_runs + eval_results.

``eval_runs`` holds one row per run (status + summary JSONB); ``eval_results``
holds one row per case result and rides the existing PostgresCollectionStore
(scope_key = run_id), so its GIN-indexed metadata filters by test_case_id /
passed / resolved_prompt_version_id.

Schema owned by the migration (docs/eval-prompt-store-schema.sql). ``eval_runs``
FKs suites + prompt_versions — both must exist before create_run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ryuu_storage_postgres._pool import get_pool
from ryuu_storage_postgres.collection import PostgresCollectionStore


def _epoch(dt: datetime | None) -> float | None:
    return dt.timestamp() if dt is not None else None


@dataclass
class PostgresEvalRunStore:
    """Persistent ``IEvalRunStore``: eval_runs row + eval_results collection."""

    dsn: str
    runs_table: str = "eval_runs"
    results_table: str = "eval_results"
    _results: PostgresCollectionStore = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.runs_table.replace("_", "").isalnum():
            raise ValueError(f"Invalid table name: {self.runs_table!r}")
        self._results = PostgresCollectionStore(dsn=self.dsn, table=self.results_table)

    async def create_run(
        self,
        run_id: str,
        suite_id: str,
        *,
        prompt_version_id: str | None = None,
        triggered_by: str = "",
        trigger_type: str = "manual",
    ) -> None:
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            await conn.execute(
                f"INSERT INTO {self.runs_table}"
                f" (id, suite_id, prompt_version_id, triggered_by, trigger_type, status, started_at)"
                f" VALUES($1, $2, $3, $4, $5, 'running', now())"
                f" ON CONFLICT (id) DO NOTHING",
                run_id, suite_id, prompt_version_id, triggered_by, trigger_type,
            )

    async def finish_run(self, run_id: str, *, status: str, summary: dict[str, Any]) -> None:
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            await conn.execute(
                f"UPDATE {self.runs_table}"
                f" SET status = $2, summary = $3::jsonb, completed_at = now()"
                f" WHERE id = $1",
                run_id, status, json.dumps(summary, default=str),
            )

    async def save_result(
        self,
        run_id: str,
        result: dict[str, Any],
        *,
        test_case_id: str,
        passed: bool,
        resolved_prompt_version_id: str | None = None,
    ) -> None:
        await self._results.append(
            run_id,
            json.dumps(result, default=str),
            metadata={
                "test_case_id": test_case_id,
                "passed": passed,
                "resolved_prompt_version_id": resolved_prompt_version_id,
            },
        )

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT * FROM {self.runs_table} WHERE id = $1", run_id
            )
        if row is None:
            return None
        items = await self._results.list(run_id, limit=10_000)
        cases = [json.loads(it.content) for it in items]
        return {**self._row_to_dict(row), "cases": cases}

    async def list_runs(self, suite_id: str, limit: int = 20) -> list[dict[str, Any]]:
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM {self.runs_table} WHERE suite_id = $1"
                f" ORDER BY started_at DESC LIMIT $2",
                suite_id, max(1, limit),
            )
        return [self._row_to_dict(r) for r in rows]

    @staticmethod
    def _row_to_dict(row) -> dict[str, Any]:
        summary = row["summary"]
        if isinstance(summary, str):
            summary = json.loads(summary)
        return {
            "run_id": row["id"],
            "suite_id": row["suite_id"],
            "prompt_version_id": row["prompt_version_id"],
            "triggered_by": row["triggered_by"],
            "trigger_type": row["trigger_type"],
            "status": row["status"],
            "summary": summary or {},
            "started_at": _epoch(row["started_at"]),
            "completed_at": _epoch(row["completed_at"]),
        }
