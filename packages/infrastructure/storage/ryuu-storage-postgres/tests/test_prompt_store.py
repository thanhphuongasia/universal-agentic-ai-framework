"""Tests for PostgresPromptStore against the eval migration schema.

Requires a live Postgres instance. Skipped automatically when DATABASE_URL is not set.
The migration (docs/eval-prompt-store-schema.sql) is applied fresh per module.

Run:
    DATABASE_URL=postgresql://postgres:test@localhost/ryuu_test pytest tests/test_prompt_store.py
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from ryuu_prompts import (
    PromptConfig,
    PromptStatus,
    PromptStoreError,
    PromptTemplate,
    PromptVersion,
    PromptVersionNotFoundError,
)
from ryuu_storage_postgres import PostgresPromptStore, close_all
from ryuu_storage_postgres._pool import get_pool

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL not set — skipping Postgres tests",
)

DSN = os.getenv("DATABASE_URL", "")
MIGRATION = Path(__file__).parents[5] / "docs" / "eval-prompt-store-schema.sql"

# Eval tables in FK-safe drop order (children → parents).
_EVAL_TABLES = [
    "eval_results", "eval_runs", "test_cases", "templates",
    "prompt_versions", "suites", "domains", "systems", "prompt_active",
]


def _suite() -> str:
    return f"suite_{uuid.uuid4().hex}"


def _config(version: str) -> PromptConfig:
    return PromptConfig(
        version=version, description="test", model="gpt-4o-mini",
        temperature=0.2, max_tokens=512,
        prompts={"analyze": PromptTemplate(system="You are {role}.", user="{query}")},
    )


def _version(suite: str, ver: str, *, created_at: float = 0.0) -> PromptVersion:
    return PromptVersion(
        id=f"{suite}-{ver}", suite_id=suite, version=ver,
        config=_config(ver), created_at=created_at,
    )


@pytest.fixture(scope="module", autouse=True)
async def migrate():
    """Apply the migration fresh (drop eval tables, re-create from the .sql file)."""
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


@pytest.fixture
async def store():
    return PostgresPromptStore(dsn=DSN)


async def _make_suite(store: PostgresPromptStore) -> str:
    """Create system → domain → suite chain; return the suite id."""
    suite = _suite()
    sys_id, dom_id = f"sys_{uuid.uuid4().hex}", f"dom_{uuid.uuid4().hex}"
    pool = await get_pool(DSN)
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO systems(id, name) VALUES($1, $2)", sys_id, "test-sys")
        await conn.execute(
            "INSERT INTO domains(id, system_id, name) VALUES($1, $2, $3)",
            dom_id, sys_id, f"dom-{suite}",
        )
    await store.ensure_suite(suite, domain_id=dom_id, name=suite)
    return suite


# --- save / get / list (config + status round-trip through JSONB) ---------


async def test_save_get_roundtrip(store):
    suite = await _make_suite(store)
    v = _version(suite, "v1")
    await store.save(v)
    got = await store.get(suite, "v1")
    assert got is not None
    assert got.config == v.config
    assert got.status is PromptStatus.DRAFT
    assert await store.get(suite, "missing") is None


async def test_save_upsert_updates(store):
    suite = await _make_suite(store)
    await store.save(_version(suite, "v1"))
    await store.set_status(suite, "v1", PromptStatus.STAGING)
    v2 = _version(suite, "v1")
    v2.config = _config("v1-edited")
    await store.save(v2)
    rows = await store.list_versions(suite)
    assert len(rows) == 1
    assert rows[0].config.version == "v1-edited"


async def test_list_versions_sorted_and_scoped(store):
    suite_a = await _make_suite(store)
    suite_b = await _make_suite(store)
    await store.save(_version(suite_a, "v2", created_at=2.0))
    await store.save(_version(suite_a, "v1", created_at=1.0))
    await store.save(_version(suite_b, "v9", created_at=9.0))
    versions = await store.list_versions(suite_a)
    assert [v.version for v in versions] == ["v1", "v2"]
    assert all(v.suite_id == suite_a for v in versions)


# --- lifecycle: status ----------------------------------------------------


async def test_set_status(store):
    suite = await _make_suite(store)
    await store.save(_version(suite, "v1"))
    updated = await store.set_status(suite, "v1", PromptStatus.STAGING)
    assert updated.status is PromptStatus.STAGING
    assert (await store.get(suite, "v1")).status is PromptStatus.STAGING


async def test_set_status_missing_raises(store):
    suite = await _make_suite(store)
    with pytest.raises(PromptVersionNotFoundError):
        await store.set_status(suite, "nope", PromptStatus.STAGING)


# --- lifecycle: promote + active pointer (suites.active_prompt_version_id) -


async def test_promote_sets_active_and_stamps(store):
    suite = await _make_suite(store)
    await store.save(_version(suite, "v1"))
    assert await store.get_active(suite) is None

    promoted = await store.promote(suite, "v1", by="alice")
    assert promoted.promoted_by == "alice"
    assert promoted.promoted_at is not None and promoted.promoted_at > 0
    assert (await store.get_active(suite)).version == "v1"


async def test_promote_moves_pointer(store):
    suite = await _make_suite(store)
    await store.save(_version(suite, "v1"))
    await store.save(_version(suite, "v2"))
    await store.promote(suite, "v1", by="alice")
    await store.promote(suite, "v2", by="bob")
    assert (await store.get_active(suite)).version == "v2"


async def test_promote_archived_blocked(store):
    suite = await _make_suite(store)
    await store.save(_version(suite, "v1"))
    await store.set_status(suite, "v1", PromptStatus.ARCHIVED)
    with pytest.raises(PromptStoreError):
        await store.promote(suite, "v1", by="alice")


async def test_promote_missing_raises(store):
    suite = await _make_suite(store)
    with pytest.raises(PromptVersionNotFoundError):
        await store.promote(suite, "nope", by="alice")
