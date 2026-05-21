"""Unit tests for EpisodicMemoryStore — P3-T04."""

from __future__ import annotations

import pytest

from ryuu.knowledge.memory.episodic import EpisodicMemoryStore
from ryuu.knowledge.memory.store import MemoryLayer


class TestEpisodicMemoryStore:
    @pytest.mark.asyncio
    async def test_store_and_retrieve_keyword_match(self):
        store = EpisodicMemoryStore()
        await store.store("Python async programming", scope_key="s1")
        results = await store.retrieve("async", scope_key="s1")
        assert len(results) == 1
        assert results[0].content == "Python async programming"

    @pytest.mark.asyncio
    async def test_no_match_returns_empty(self):
        store = EpisodicMemoryStore()
        await store.store("Python async programming", scope_key="s1")
        results = await store.retrieve("JavaScript", scope_key="s1")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_top_k_limit(self):
        store = EpisodicMemoryStore()
        for i in range(5):
            await store.store(f"python entry {i}", scope_key="s1")
        results = await store.retrieve("python", scope_key="s1", top_k=3)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_score_higher_overlap(self):
        store = EpisodicMemoryStore()
        await store.store("python async code", scope_key="s1")
        await store.store("python sync", scope_key="s1")
        results = await store.retrieve("python async", scope_key="s1")
        # Entry with more matching words should score higher
        assert results[0].content == "python async code"

    @pytest.mark.asyncio
    async def test_scope_isolation(self):
        store = EpisodicMemoryStore()
        await store.store("secret data", scope_key="s1")
        results = await store.retrieve("secret", scope_key="s2")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_clear(self):
        store = EpisodicMemoryStore()
        await store.store("data", scope_key="s1")
        await store.clear("s1")
        results = await store.retrieve("data", scope_key="s1")
        assert len(results) == 0

    def test_layer(self):
        assert EpisodicMemoryStore().layer == MemoryLayer.EPISODIC
