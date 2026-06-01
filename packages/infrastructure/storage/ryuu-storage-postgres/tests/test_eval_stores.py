"""Tests for PostgresTestCaseStore + PostgresEvalRunStore against the eval schema.

Requires a live Postgres. Skipped when DATABASE_URL is not set. The migration
(docs/eval-prompt-store-schema.sql) is applied fresh per module.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from ryuu_eval_core.models import EvalCase
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
MIGRATION = Path(__file__).parents[5] / "docs" / "eval-prompt-store-schema.sql"
_EVAL_TABLES = [
    "eval_results", "eval_runs", "test_cases", "templates",
    "prompt_versions", "suites", "domains", "systems", "prompt_active",
]


@pytest.fixture(scope="module", autouse=True)
async def migrate():
    pool = await get_pool(DSN)
    async with pool.acquire() as conn:
        for t in _EVAL_TABLES:
            await conn.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
        await conn.execute(MIGRATION.read_text())
    await close_all()
    yield


@pytest.fixture(autouse=True)
async def cleanup():
    yield
    await close_all()


async def _make_suite() -> str:
    suite = f"suite_{uuid.uuid4().hex}"
    sys_id, dom_id = f"sys_{uuid.uuid4().hex}", f"dom_{uuid.uuid4().hex}"
    pool = await get_pool(DSN)
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO systems(id, name) VALUES($1, 's')", sys_id)
        await conn.execute(
            "INSERT INTO domains(id, system_id, name) VALUES($1, $2, 'd')", dom_id, sys_id
        )
        await conn.execute(
            "INSERT INTO suites(id, domain_id, name) VALUES($1, $2, $1)", suite, dom_id
        )
    return suite


# --- PostgresTestCaseStore ------------------------------------------------


async def test_save_list_case_with_scoring():
    suite = await _make_suite()
    store = PostgresTestCaseStore(dsn=DSN)
    case = EvalCase(
        case_id="tc1", input={"code": "x"}, expected={"ok": True},
        metadata={"scoring": {"scorers": [{"type": "contains", "config": {"required": ["A"]}}]}},
    )
    await store.save_case(suite, case)

    cases = await store.list_cases(suite)
    assert len(cases) == 1
    got = cases[0]
    assert got.case_id == "tc1"
    assert got.input == {"code": "x"}
    assert got.expected == {"ok": True}
    # scoring spec surfaced back into metadata → feeds metadata_scorer_resolver
    assert got.metadata["scoring"]["scorers"][0]["type"] == "contains"


async def test_get_and_delete_case():
    suite = await _make_suite()
    store = PostgresTestCaseStore(dsn=DSN)
    await store.save_case(suite, EvalCase(case_id="tc1", input="i", expected="e"))
    assert (await store.get_case(suite, "tc1")).input == "i"
    assert await store.delete_case(suite, "tc1") is True
    assert await store.get_case(suite, "tc1") is None
    assert await store.delete_case(suite, "tc1") is False


async def test_cases_scoped_to_suite():
    a, b = await _make_suite(), await _make_suite()
    store = PostgresTestCaseStore(dsn=DSN)
    await store.save_case(a, EvalCase(case_id="x", input="1"))
    await store.save_case(b, EvalCase(case_id="y", input="2"))
    assert [c.case_id for c in await store.list_cases(a)] == ["x"]


async def test_prompt_override_id_roundtrips():
    suite = await _make_suite()
    # prompt_override_id FKs prompt_versions(id) — create one first.
    pool = await get_pool(DSN)
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO prompt_versions(id, suite_id, version, config)"
            " VALUES('pv_x', $1, 'v1', '{}'::jsonb)", suite)
    store = PostgresTestCaseStore(dsn=DSN)
    await store.save_case(
        suite, EvalCase(case_id="tc1", input="i", metadata={"prompt_override_id": "pv_x"}))
    got = await store.get_case(suite, "tc1")
    assert got.metadata["prompt_override_id"] == "pv_x"


# --- PostgresEvalRunStore -------------------------------------------------


async def test_run_lifecycle_and_results():
    suite = await _make_suite()
    store = PostgresEvalRunStore(dsn=DSN)
    run_id = uuid.uuid4().hex

    await store.create_run(run_id, suite, triggered_by="tester")
    running = await store.get_run(run_id)
    assert running["status"] == "running"
    assert running["cases"] == []

    await store.save_result(run_id, {"output": "A", "passed": True},
                            test_case_id="tc1", passed=True)
    await store.save_result(run_id, {"output": "B", "passed": False},
                            test_case_id="tc2", passed=False)
    await store.finish_run(run_id, status="completed",
                           summary={"total": 2, "passed": 1, "pass_rate": 0.5})

    done = await store.get_run(run_id)
    assert done["status"] == "completed"
    assert done["summary"]["pass_rate"] == 0.5
    assert {c["output"] for c in done["cases"]} == {"A", "B"}


async def test_list_runs_newest_first():
    suite = await _make_suite()
    store = PostgresEvalRunStore(dsn=DSN)
    r1, r2 = uuid.uuid4().hex, uuid.uuid4().hex
    await store.create_run(r1, suite)
    await store.create_run(r2, suite)
    runs = await store.list_runs(suite, limit=10)
    assert {r["run_id"] for r in runs} == {r1, r2}
    assert all(r["suite_id"] == suite for r in runs)


async def test_get_run_missing_returns_none():
    store = PostgresEvalRunStore(dsn=DSN)
    assert await store.get_run("does-not-exist") is None
