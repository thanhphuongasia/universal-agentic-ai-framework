"""Unit tests for WorkingMemoryStore — P3-T03."""

from __future__ import annotations

import pytest

from uaaf.knowledge.memory.store import MemoryLayer
from uaaf.knowledge.memory.working import WorkingMemoryStore


class TestWorkingMemoryStore:
    @pytest.mark.asyncio
    async def test_store_and_retrieve(self):
        store = WorkingMemoryStore()
        await store.store("hello world", scope_key="s1")
        results = await store.retrieve("hello", scope_key="s1")
        assert len(results) == 1
        assert results[0].content == "hello world"

    @pytest.mark.asyncio
    async def test_fifo_eviction(self):
        store = WorkingMemoryStore(max_entries=2)
        await store.store("first", scope_key="s1")
        await store.store("second", scope_key="s1")
        await store.store("third", scope_key="s1")
        results = await store.retrieve("", scope_key="s1", top_k=10)
        contents = [r.content for r in results]
        assert "first" not in contents
        assert "second" in contents
        assert "third" in contents

    @pytest.mark.asyncio
    async def test_returns_most_recent_first(self):
        store = WorkingMemoryStore()
        await store.store("older", scope_key="s1")
        await store.store("newer", scope_key="s1")
        results = await store.retrieve("", scope_key="s1", top_k=2)
        assert results[0].content == "newer"

    @pytest.mark.asyncio
    async def test_scope_isolation(self):
        store = WorkingMemoryStore()
        await store.store("scope1 content", scope_key="s1")
        results = await store.retrieve("", scope_key="s2")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_clear(self):
        store = WorkingMemoryStore()
        await store.store("content", scope_key="s1")
        await store.clear(scope_key="s1")
        results = await store.retrieve("", scope_key="s1")
        assert len(results) == 0

    def test_layer(self):
        assert WorkingMemoryStore().layer == MemoryLayer.WORKING
