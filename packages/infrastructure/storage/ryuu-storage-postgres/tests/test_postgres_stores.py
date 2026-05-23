"""Tests for PostgresKVStore + PostgresCollectionStore.

Requires a live Postgres instance. Skipped automatically when DATABASE_URL is not set.

Run:
    DATABASE_URL=postgresql://postgres:test@localhost/ryuu_test pytest tests/
"""

from __future__ import annotations

import os

import pytest

from ryuu_storage_postgres import PostgresKVStore, PostgresCollectionStore, close_all

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL not set — skipping Postgres tests",
)

DSN = os.getenv("DATABASE_URL", "")


@pytest.fixture(autouse=True)
async def cleanup():
    yield
    await close_all()


# ---------------------------------------------------------------------------
# PostgresKVStore
# ---------------------------------------------------------------------------

@pytest.fixture
async def kv_store():
    store = PostgresKVStore(dsn=DSN, table="test_kv")
    from ryuu_storage_postgres._pool import get_pool
    await store._ensure_table()
    p = await get_pool(DSN)
    async with p.acquire() as conn:
        await conn.execute("DELETE FROM test_kv")
    yield store


class TestPostgresKVStore:
    async def test_put_and_get(self, kv_store):
        await kv_store.put("hello", "world")
        assert await kv_store.get("hello") == "world"

    async def test_get_missing_returns_none(self, kv_store):
        assert await kv_store.get("nope") is None

    async def test_put_overwrites(self, kv_store):
        await kv_store.put("k", "v1")
        await kv_store.put("k", "v2")
        assert await kv_store.get("k") == "v2"

    async def test_delete_existing(self, kv_store):
        await kv_store.put("x", "1")
        assert await kv_store.delete("x") is True
        assert await kv_store.get("x") is None

    async def test_delete_missing(self, kv_store):
        assert await kv_store.delete("ghost") is False

    async def test_keys_prefix(self, kv_store):
        await kv_store.put("user:1", "a")
        await kv_store.put("user:2", "b")
        await kv_store.put("other", "c")
        result = list(await kv_store.keys(prefix="user:"))
        assert sorted(result) == ["user:1", "user:2"]

    async def test_keys_all(self, kv_store):
        await kv_store.put("a", "1")
        await kv_store.put("b", "2")
        result = list(await kv_store.keys())
        assert "a" in result and "b" in result


# ---------------------------------------------------------------------------
# PostgresCollectionStore
# ---------------------------------------------------------------------------

@pytest.fixture
async def coll_store():
    store = PostgresCollectionStore(dsn=DSN, table="test_coll")
    from ryuu_storage_postgres._pool import get_pool
    await store._ensure_table()
    p = await get_pool(DSN)
    async with p.acquire() as conn:
        await conn.execute("DELETE FROM test_coll")
    yield store


class TestPostgresCollectionStore:
    async def test_append_and_get(self, coll_store):
        item_id = await coll_store.append("scope1", "hello world", {"tag": "test"})
        item = await coll_store.get("scope1", item_id)
        assert item is not None
        assert item.content == "hello world"
        assert item.metadata == {"tag": "test"}

    async def test_get_wrong_scope_returns_none(self, coll_store):
        item_id = await coll_store.append("scope1", "content")
        assert await coll_store.get("scope2", item_id) is None

    async def test_list_ordered_by_time(self, coll_store):
        await coll_store.append("s", "first")
        await coll_store.append("s", "second")
        await coll_store.append("s", "third")
        items = await coll_store.list("s")
        assert [i.content for i in items] == ["first", "second", "third"]

    async def test_list_limit(self, coll_store):
        for i in range(5):
            await coll_store.append("s", f"item{i}")
        items = await coll_store.list("s", limit=3)
        assert len(items) == 3

    async def test_search_ilike(self, coll_store):
        await coll_store.append("s", "User thích cà phê đen")
        await coll_store.append("s", "Hôm nay trời đẹp")
        results = await coll_store.search("s", "cà phê")
        assert len(results) == 1
        assert "cà phê" in results[0].content

    async def test_search_case_insensitive(self, coll_store):
        await coll_store.append("s", "PostgreSQL is great")
        results = await coll_store.search("s", "postgresql")
        assert len(results) == 1

    async def test_update_content(self, coll_store):
        item_id = await coll_store.append("s", "old content")
        await coll_store.update("s", item_id, content="new content")
        item = await coll_store.get("s", item_id)
        assert item.content == "new content"

    async def test_delete(self, coll_store):
        item_id = await coll_store.append("s", "to delete")
        assert await coll_store.delete("s", item_id) is True
        assert await coll_store.get("s", item_id) is None

    async def test_clear_scope(self, coll_store):
        await coll_store.append("s1", "a")
        await coll_store.append("s1", "b")
        await coll_store.append("s2", "c")
        await coll_store.clear("s1")
        assert await coll_store.list("s1") == []
        assert len(await coll_store.list("s2")) == 1

    async def test_scope_isolation(self, coll_store):
        await coll_store.append("user_A", "private note A")
        await coll_store.append("user_B", "private note B")
        a_items = await coll_store.list("user_A")
        b_items = await coll_store.list("user_B")
        assert len(a_items) == 1
        assert len(b_items) == 1
        assert a_items[0].content != b_items[0].content
