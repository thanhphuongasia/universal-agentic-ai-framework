"""InvestigationStore Protocol + create_store() factory.

Same shape as prod-grade-code-analysis/src/contexts/eval/application/
ingestion_investigator/store.py (commit a2a1100).

Two backends:
    INVESTIGATION_DB_BACKEND=postgres  (default)
    INVESTIGATION_DB_BACKEND=sqlite
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol, runtime_checkable

from .models import RootCauseReport

# Auto-load .env from cwd or any parent dir, once at import time.
# Idempotent — does nothing if no .env exists.
try:
    from dotenv import load_dotenv  # type: ignore[import-not-found]
    load_dotenv()  # searches cwd and parents
except ImportError:
    pass  # python-dotenv optional; env vars still work


@runtime_checkable
class InvestigationStore(Protocol):
    def save(self, case_id: str, suite_id: str, report: RootCauseReport) -> None: ...
    def get_by_case(self, case_id: str) -> RootCauseReport | None: ...
    def list_by_suite(self, suite_id: str) -> list[dict]: ...
    def get_full_by_case(self, case_id: str) -> dict | None: ...


def create_store(
    backend: str | None = None,
    dsn: str | None = None,
    db_path: Path | None = None,
) -> InvestigationStore:
    """Factory — reads env vars by default:
    INVESTIGATION_DB_BACKEND, INVESTIGATION_DB_DSN, INVESTIGATIONS_DB_PATH.
    """
    resolved = (backend or os.getenv("INVESTIGATION_DB_BACKEND", "postgres")).lower()

    if resolved == "postgres":
        from .postgres_store import PostgresInvestigationStore
        resolved_dsn = dsn or os.getenv(
            "INVESTIGATION_DB_DSN",
            "postgresql://localhost:5432/investigations",
        )
        return PostgresInvestigationStore(dsn=resolved_dsn)

    if resolved == "sqlite":
        from .sqlite_store import SqliteInvestigationStore
        resolved_path = db_path or Path(
            os.getenv("INVESTIGATIONS_DB_PATH", "artifacts/state/investigations.sqlite3")
        )
        return SqliteInvestigationStore(db_path=resolved_path)

    raise ValueError(
        f"Unknown INVESTIGATION_DB_BACKEND={resolved!r}. "
        "Valid: 'postgres', 'sqlite'."
    )
