"""Tests for PostgresSuiteStore. Skipped when DATABASE_URL is not set."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from ryuu_eval_core.models import EvalCase
from ryuu_storage_postgres import PostgresSuiteStore, PostgresTestCaseStore, close_all
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
        await conn.execute("INSERT INTO systems(id, name) VALUES('s', 's')")
        await conn.execute("INSERT INTO domains(id, system_id, name) VALUES('d', 's', 'd')")
    await close_all()
    yield


@pytest.fixture(autouse=True)
async def cleanup():
    yield
    await close_all()


async def test_create_list_get():
    store = PostgresSuiteStore(dsn=DSN)
    sid = f"suite_{uuid.uuid4().hex}"
    await store.create_suite(sid, title="My Suite", domain_id="d")

    listed = await store.list_suites()
    assert any(s["suite_id"] == sid and s["title"] == "My Suite" for s in listed)

    got = await store.get_suite(sid)
    assert got is not None and got["title"] == "My Suite" and got["case_count"] == 0
    assert await store.get_suite("nope") is None


async def test_case_count_reflects_cases():
    store = PostgresSuiteStore(dsn=DSN)
    tc = PostgresTestCaseStore(dsn=DSN)
    sid = f"suite_{uuid.uuid4().hex}"
    await store.create_suite(sid, title=sid, domain_id="d")
    await tc.save_case(sid, EvalCase(case_id="c1", input="x"))
    await tc.save_case(sid, EvalCase(case_id="c2", input="y"))
    assert (await store.get_suite(sid))["case_count"] == 2


async def test_delete_cascades():
    store = PostgresSuiteStore(dsn=DSN)
    tc = PostgresTestCaseStore(dsn=DSN)
    sid = f"suite_{uuid.uuid4().hex}"
    await store.create_suite(sid, title=sid, domain_id="d")
    await tc.save_case(sid, EvalCase(case_id="c1", input="x"))

    assert await store.delete_suite(sid) is True
    assert await store.get_suite(sid) is None
    assert await tc.list_cases(sid) == []        # FK cascade removed cases
    assert await store.delete_suite(sid) is False  # already gone
