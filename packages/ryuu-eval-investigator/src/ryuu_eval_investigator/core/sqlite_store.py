"""SQLite backend for InvestigationStore.

Follows the same sqlite3 + threading.Lock pattern as src/contexts/chat/memory.py.
Use INVESTIGATION_DB_BACKEND=sqlite to activate.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from .models import RootCauseReport


class SqliteInvestigationStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._lock = Lock()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS investigation_reports (
                    case_id     TEXT PRIMARY KEY,
                    suite_id    TEXT NOT NULL DEFAULT '',
                    target_id    TEXT NOT NULL DEFAULT '',
                    report_json TEXT NOT NULL,
                    created_at  TEXT NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_suite ON investigation_reports(suite_id)"
            )
            conn.commit()

    def save(self, case_id: str, suite_id: str, report: RootCauseReport) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO investigation_reports(case_id, suite_id, target_id, report_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(case_id) DO UPDATE SET
                    suite_id    = excluded.suite_id,
                    target_id    = excluded.target_id,
                    report_json = excluded.report_json,
                    created_at  = excluded.created_at
                """,
                (case_id, suite_id, report.target_id, report.model_dump_json(), now),
            )
            conn.commit()

    def get_by_case(self, case_id: str) -> RootCauseReport | None:
        with self._lock, sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT report_json FROM investigation_reports WHERE case_id = ?",
                (case_id,),
            ).fetchone()
        if row is None:
            return None
        return RootCauseReport.model_validate_json(row[0])

    def list_by_suite(self, suite_id: str) -> list[dict]:
        with self._lock, sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT case_id, target_id, created_at, report_json
                FROM investigation_reports
                WHERE suite_id = ?
                ORDER BY created_at DESC
                """,
                (suite_id,),
            ).fetchall()
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
        with self._lock, sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT suite_id, target_id, report_json, created_at "
                "FROM investigation_reports WHERE case_id = ?",
                (case_id,),
            ).fetchone()
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
