"""Oracle Studio promote-to-suite lands a case in the DB (test_case_store).

Verifies the integration: a reviewed oracle fixture promoted to a suite shows up
in the DB-only cases list (not just a YAML file).
Requires DATABASE_URL.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from ryuu_eval_core import EvalRunner
from ryuu_eval.http.router import build_eval_router
from ryuu_storage_postgres import PostgresSuiteStore, PostgresTestCaseStore, close_all
from ryuu_storage_postgres._pool import get_pool

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL not set — skipping Postgres tests",
)

DSN = os.getenv("DATABASE_URL", "")
MIGRATION = Path(__file__).resolve().parents[1].parent / "docs" / "eval-prompt-store-schema.sql"
_EVAL_TABLES = [
    "eval_results", "eval_runs", "test_cases", "templates",
    "prompt_versions", "suites", "domains", "systems", "prompt_active",
]


async def test_promote_oracle_fixture_lands_in_db_cases(tmp_path):
    # fresh schema + a default domain for suite creation
    pool = await get_pool(DSN)
    async with pool.acquire() as conn:
        for t in _EVAL_TABLES:
            await conn.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
        await conn.execute(MIGRATION.read_text())
        await conn.execute("INSERT INTO systems(id, name) VALUES('eval', 'Eval')")
        await conn.execute("INSERT INTO domains(id, system_id, name) VALUES('eval-default', 'eval', 'D')")

    # a minimal v0 oracle fixture on disk
    oracle_dir = tmp_path / "oracle"
    oracle_dir.mkdir()
    fixture_id = f"fx_{uuid.uuid4().hex}"
    (oracle_dir / f"{fixture_id}.json").write_text(json.dumps({
        "input_data": {"code": "class OrderController {}"},
        "expected": {"Order": {"id": {"op": "CR"}}},
        "oracle_model": "claude-sonnet-4-6",
    }))

    suite = f"suite_{uuid.uuid4().hex}"
    tc_store = PostgresTestCaseStore(dsn=DSN)
    suite_store = PostgresSuiteStore(dsn=DSN)
    app = FastAPI()
    app.include_router(build_eval_router(
        runner_factory=lambda s, p: EvalRunner(suite_id=s, target=None, scorers=[]),
        template_registry={},
        test_case_store=tc_store, suite_store=suite_store,
        prompt_default_domain_id="eval-default", oracle_fixtures_dir=oracle_dir,
    ), prefix="/api/eval")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/api/eval/oracle-review/{fixture_id}/promote-to-suite",
                         json={"target_suite_id": suite, "case_id": "promoted_case"})
        assert r.status_code == 200, r.text
        assert r.json()["written_path"].startswith("db:")

        # the promoted case is now in the DB-only cases list + suite case_count
        cases = (await c.get(f"/api/eval/suites/{suite}/cases")).json()
        meta = (await c.get(f"/api/eval/suites/{suite}")).json()

    await close_all()

    assert [x["case_id"] for x in cases] == ["promoted_case"]
    assert cases[0]["expected"]["cells"] == [{"entity": "Order", "column": "id", "op": "CR"}]
    assert cases[0]["metadata"]["source_fixture"] == fixture_id
    assert meta["case_count"] == 1
