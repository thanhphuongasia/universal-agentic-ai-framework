"""PostgresTestCaseStore — ITestCaseStore over the migration's test_cases table.

Maps a ``test_cases`` row ↔ ``EvalCase``. The per-case scoring spec
(``test_cases.scoring`` JSONB) is surfaced as ``EvalCase.metadata['scoring']`` so
it flows straight into ``metadata_scorer_resolver`` — DB cases get per-case
scoring for free. ``test_cases.name`` and ``template_id`` are surfaced under
``metadata`` too (the runner ignores them; the listing UI uses them).

Schema is owned by the migration (docs/eval-prompt-store-schema.sql); this store
does not create tables. ``test_cases.suite_id`` FKs ``suites`` — the suite must
exist (see PostgresPromptStore.ensure_suite).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ryuu_eval_core.models import EvalCase

from ryuu_storage_postgres._pool import get_pool


def _jsonb(value: Any) -> Any:
    """asyncpg may hand JSONB back as str — normalize to a Python object."""
    if isinstance(value, str):
        return json.loads(value)
    return value


@dataclass
class PostgresTestCaseStore:
    """Persistent ``ITestCaseStore`` over the test_cases table."""

    dsn: str
    table: str = "test_cases"

    def __post_init__(self) -> None:
        if not self.table.replace("_", "").isalnum():
            raise ValueError(f"Invalid table name: {self.table!r}")

    @staticmethod
    def _row_to_case(row) -> EvalCase:
        metadata = dict(_jsonb(row["metadata"]) or {})
        scoring = _jsonb(row["scoring"]) or {}
        if scoring:
            metadata["scoring"] = scoring
        if row["name"] is not None:
            metadata.setdefault("name", row["name"])
        if row["template_id"] is not None:
            metadata.setdefault("template_id", row["template_id"])
        return EvalCase(
            case_id=row["id"],
            input=_jsonb(row["input"]),
            expected=_jsonb(row["expected"]),
            metadata=metadata,
        )

    async def list_cases(self, suite_id: str) -> list[EvalCase]:
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM {self.table} WHERE suite_id = $1"
                f" ORDER BY created_at ASC, id ASC",
                suite_id,
            )
            return [self._row_to_case(r) for r in rows]

    async def get_case(self, suite_id: str, case_id: str) -> EvalCase | None:
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT * FROM {self.table} WHERE suite_id = $1 AND id = $2",
                suite_id, case_id,
            )
            return self._row_to_case(row) if row else None

    async def save_case(
        self,
        suite_id: str,
        case: EvalCase,
        *,
        template_id: str | None = None,
        scoring: dict[str, Any] | None = None,
    ) -> None:
        # scoring: explicit arg wins, else lifted from metadata['scoring'].
        meta = dict(case.metadata or {})
        eff_scoring = scoring if scoring is not None else meta.pop("scoring", None)
        name = meta.pop("name", None) or case.case_id
        eff_template = template_id or meta.pop("template_id", None)
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            await conn.execute(
                f"INSERT INTO {self.table}"
                f" (id, suite_id, template_id, name, input, expected, scoring, metadata)"
                f" VALUES($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7::jsonb, $8::jsonb)"
                f" ON CONFLICT (suite_id, id) DO UPDATE SET"
                f"   template_id = EXCLUDED.template_id,"
                f"   name        = EXCLUDED.name,"
                f"   input       = EXCLUDED.input,"
                f"   expected    = EXCLUDED.expected,"
                f"   scoring     = EXCLUDED.scoring,"
                f"   metadata    = EXCLUDED.metadata",
                case.case_id, suite_id, eff_template, name,
                json.dumps(case.input), json.dumps(case.expected),
                json.dumps(eff_scoring or {}), json.dumps(meta),
            )

    async def delete_case(self, suite_id: str, case_id: str) -> bool:
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            result = await conn.execute(
                f"DELETE FROM {self.table} WHERE suite_id = $1 AND id = $2",
                suite_id, case_id,
            )
            return result.split()[-1] != "0"
