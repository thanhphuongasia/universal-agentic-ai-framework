"""Slice 3 integration: router reads cases from DB and persists runs to DB.

Requires a live Postgres (DATABASE_URL). Applies the migration fresh, seeds a
suite + two cases (with per-case scoring), then drives a run through the HTTP
router with a stub target and asserts the run + results land in eval_runs/eval_results.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from ryuu_eval_core import EvalCaseTemplate, EvalRunner
from ryuu_eval_core.models import CaseResult, EvalCase
from ryuu_eval.http.router import build_eval_router
from ryuu_eval_scorers import ExactMatch, metadata_scorer_resolver
from ryuu_storage_postgres import (
    PostgresEvalRunStore,
    PostgresTestCaseStore,
    close_all,
)
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


class _StubTarget:
    """Returns a fixed output so scoring is deterministic (no LLM)."""
    model = "stub"

    async def run(self, case: EvalCase) -> CaseResult:
        return CaseResult(case=case, output="CREATE READ")


def _runner_factory(suite_id, log_path, model=None, system_prompt=None, **_kw):
    return EvalRunner(
        suite_id=suite_id, target=_StubTarget(), scorers=[ExactMatch()],
        scorer_for=metadata_scorer_resolver(),
    )


async def _seed() -> str:
    suite = f"suite_{uuid.uuid4().hex}"
    sys_id, dom_id = f"sys_{uuid.uuid4().hex}", f"dom_{uuid.uuid4().hex}"
    pool = await get_pool(DSN)
    async with pool.acquire() as conn:
        for t in _EVAL_TABLES:
            await conn.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
        await conn.execute(MIGRATION.read_text())
        await conn.execute("INSERT INTO systems(id, name) VALUES($1, 's')", sys_id)
        await conn.execute(
            "INSERT INTO domains(id, system_id, name) VALUES($1, $2, 'd')", dom_id, sys_id)
        await conn.execute(
            "INSERT INTO suites(id, domain_id, name) VALUES($1, $2, $1)", suite, dom_id)

    tc_store = PostgresTestCaseStore(dsn=DSN)
    # passes: requires CREATE/READ, forbids GraphQL — output "CREATE READ" is clean
    await tc_store.save_case(suite, EvalCase(
        case_id="orders", input="x", expected="x",
        metadata={"scoring": {"scorers": [{"type": "contains", "config": {"required": ["CREATE", "READ"]}}],
                              "forbidden": ["GraphQL"]}}))
    # fails: requires all four ops — output lacks UPDATE/DELETE
    await tc_store.save_case(suite, EvalCase(
        case_id="users", input="x", expected="x",
        metadata={"scoring": {"scorers": [{"type": "contains",
                  "config": {"required": ["CREATE", "READ", "UPDATE", "DELETE"]}}]}}))
    return suite


async def test_router_db_cases_and_run_persistence():
    suite = await _seed()
    tc_store = PostgresTestCaseStore(dsn=DSN)
    run_store = PostgresEvalRunStore(dsn=DSN)

    tpl = EvalCaseTemplate(template_id="t", suite_id=suite, title="T",
                           input_schema={"type": "object"}, examples=[])
    router = build_eval_router(
        runner_factory=_runner_factory, template_registry={"t": tpl},
        test_case_store=tc_store, run_store=run_store,
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/eval")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        # 1. cases come from the DB, with per-case scoring in metadata
        cases = (await c.get(f"/api/eval/suites/{suite}/cases")).json()
        assert {x["case_id"] for x in cases} == {"orders", "users"}
        assert any("scoring" in x["metadata"] for x in cases)

        # 2. start a run; drain the SSE stream so the background task completes
        run_id = (await c.post("/api/eval/run", json={"suite_id": suite, "model": "stub"})).json()["run_id"]
        async with c.stream("GET", f"/api/eval/run/stream/{run_id}") as resp:
            async for _ in resp.aiter_lines():
                pass

        # 3. wait for the background persistence to settle (status flips last),
        # then read back through the HTTP read paths (which resolve from run_store).
        run = None
        for _ in range(60):
            run = await run_store.get_run(run_id)
            if run and run["status"] == "completed":
                break
            await asyncio.sleep(0.05)
        result = (await c.get(f"/api/eval/runs/{run_id}")).json()
        runs = (await c.get(f"/api/eval/suites/{suite}/runs")).json()

    await close_all()

    # underlying normalized run row
    assert run is not None and run["status"] == "completed"
    assert run["summary"]["passed_count"] == 1
    # GET /runs/{id} — flattened from run_store; per-case scoring applied
    assert {x["case_id"] for x in result["cases"]} == {"orders", "users"}
    assert {x["case_id"]: x["pass"] for x in result["cases"]} == {"orders": True, "users": False}
    # GET /suites/{id}/runs — history from run_store
    assert any(r["run_id"] == run_id for r in runs)
