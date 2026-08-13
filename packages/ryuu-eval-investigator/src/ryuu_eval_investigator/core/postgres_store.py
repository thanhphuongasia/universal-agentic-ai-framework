"""PostgreSQL backend for InvestigationStore.

Requires: pip install psycopg2-binary
Activate: INVESTIGATION_DB_BACKEND=postgres
          INVESTIGATION_DB_DSN=postgresql://user:pass@host:5432/dbname
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from threading import Lock

try:
    import psycopg2
except ImportError as _err:
    raise ImportError(
        "psycopg2-binary is required for the PostgreSQL investigation store.\n"
        "Install it with: pip install psycopg2-binary\n"
        "Or switch to SQLite: INVESTIGATION_DB_BACKEND=sqlite"
    ) from _err

from .models import RootCauseReport

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS investigation_reports (
    case_id     TEXT PRIMARY KEY,
    suite_id    TEXT NOT NULL DEFAULT '',
    target_id    TEXT NOT NULL DEFAULT '',
    report_json TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_investigation_suite
    ON investigation_reports(suite_id);
"""

_UPSERT = """
INSERT INTO investigation_reports(case_id, suite_id, target_id, report_json, created_at)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT(case_id) DO UPDATE SET
    suite_id    = EXCLUDED.suite_id,
    target_id    = EXCLUDED.target_id,
    report_json = EXCLUDED.report_json,
    created_at  = EXCLUDED.created_at
"""


class PostgresInvestigationStore:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._lock = Lock()
        self._ensure_schema()

    def _connect(self):  # type: ignore[return]
        return psycopg2.connect(self._dsn)

    def _ensure_schema(self) -> None:
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute(_CREATE_TABLE)
            conn.commit()

    def save(self, case_id: str, suite_id: str, report: RootCauseReport) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute(_UPSERT, (case_id, suite_id, report.target_id, report.model_dump_json(), now))
            conn.commit()

    def get_by_case(self, case_id: str) -> RootCauseReport | None:
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT report_json FROM investigation_reports WHERE case_id = %s",
                (case_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return RootCauseReport.model_validate_json(row[0])

    def list_by_suite(self, suite_id: str) -> list[dict]:
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT case_id, target_id, created_at, report_json
                FROM investigation_reports
                WHERE suite_id = %s
                ORDER BY created_at DESC
                """,
                (suite_id,),
            )
            rows = cur.fetchall()
        results = []
        for case_id, target_id, created_at, report_json in rows:
            try:
                data = json.loads(report_json)
                results.append({
                    "case_id": case_id,
                    "target_id": target_id,
                    "created_at": created_at,
                    "summary": data.get("summary", ""),
                    "finding_count": len(data.get("findings", [])),
                })
            except Exception:
                results.append({
                    "case_id": case_id,
                    "target_id": target_id,
                    "created_at": created_at,
                })
        return results

    def get_full_by_case(self, case_id: str) -> dict | None:
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT suite_id, target_id, report_json, created_at "
                "FROM investigation_reports WHERE case_id = %s",
                (case_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        suite_id, target_id, report_json, created_at = row
        return {
            "case_id": case_id,
            "suite_id": suite_id,
            "target_id": target_id,
            "created_at": created_at,
            "report": json.loads(report_json),
        }
