"""Unit tests for the memory quality layer.

Covers: MemoryEntry new fields, EpisodicMemoryStore lifecycle,
SemanticMemoryStore, EvictionJob, DreamingConsolidator (no-LLM mode).
"""

from __future__ import annotations

import time

import pytest

from ryuu_knowledge_memory.consolidator import DreamingConsolidator, EvictionJob
from ryuu_knowledge_memory.episodic import EpisodicMemoryStore
from ryuu_knowledge_memory.semantic import SemanticMemoryStore
from ryuu_knowledge_memory.store import MemoryEntry


# ── MemoryEntry ──────────────────────────────────────────────────────────────

class TestMemoryEntryFields:
    def test_defaults_backward_compat(self):
        e = MemoryEntry(content="hello")
        assert e.importance == "medium"
        assert e.status == "active"
        assert e.access_count == 0
        assert e.was_corrected is False
        assert e.superseded_by is None
        assert e.consolidated_at is None
        assert e.archived_until is None
        assert e.embedding is None
        assert len(e.id) == 32  # uuid4().hex

    def test_id_unique(self):
        a, b = MemoryEntry(content="x"), MemoryEntry(content="x")
        assert a.id != b.id


# ── EpisodicMemoryStore lifecycle ────────────────────────────────────────────

class TestEpisodicLifecycle:
    @pytest.mark.asyncio
    async def test_get_unconsolidated_returns_active_entries(self):
        store = EpisodicMemoryStore()
        await store.store("fact one", scope_key="u1")
        await store.store("fact two", scope_key="u1")
        pending = await store.get_unconsolidated("u1")
        assert len(pending) == 2

    @pytest.mark.asyncio
    async def test_mark_consolidated_updates_status(self):
        store = EpisodicMemoryStore()
        await store.store("important fact", scope_key="u1")
        entries = await store.get_unconsolidated("u1")
        assert len(entries) == 1
        entry_id = entries[0].id

        await store.mark_consolidated([entry_id])

        pending = await store.get_unconsolidated("u1")
        assert len(pending) == 0  # no longer unconsolidated

        active = await store.get_all_active("u1")
        consolidated = [e for e in active if e.status == "consolidated"]
        assert len(consolidated) == 1
        assert consolidated[0].consolidated_at is not None

    @pytest.mark.asyncio
    async def test_archive_sets_status_and_ttl(self):
        store = EpisodicMemoryStore()
        await store.store("temporary fact", scope_key="u1")
        entries = await store.get_all_active("u1")
        entry_id = entries[0].id

        await store.archive(entry_id, ttl_days=30)

        all_entries = list(store._store.get("u1", {}).values())
        archived = [e for e in all_entries if e.status == "archived"]
        assert len(archived) == 1
        assert archived[0].archived_until is not None

    @pytest.mark.asyncio
    async def test_delete_expired_archives_removes_past_ttl(self):
        store = EpisodicMemoryStore()
        await store.store("old archived fact", scope_key="u1")
        entries = await store.get_all_active("u1")
        entry_id = entries[0].id

        # Archive with ttl already in the past
        bucket = store._store["u1"]
        import dataclasses
        bucket[entry_id] = dataclasses.replace(
            bucket[entry_id],
            status="archived",
            archived_until=time.time() - 1,
        )

        await store.delete_expired_archives("u1")
        assert entry_id not in store._store.get("u1", {})

    @pytest.mark.asyncio
    async def test_retrieve_excludes_archived_entries(self):
        store = EpisodicMemoryStore()
        await store.store("python programming", scope_key="u1")
        entries = await store.get_all_active("u1")
        await store.archive(entries[0].id)

        results = await store.retrieve("python", scope_key="u1")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_importance_stored_from_metadata(self):
        store = EpisodicMemoryStore()
        await store.store("user prefers dark mode", scope_key="u1", metadata={"importance": "high"})
        entries = await store.get_all_active("u1")
        assert entries[0].importance == "high"


# ── SemanticMemoryStore ──────────────────────────────────────────────────────

class TestSemanticMemoryStore:
    @pytest.mark.asyncio
    async def test_store_and_keyword_retrieve(self):
        sem = SemanticMemoryStore()
        await sem.store("user prefers dark mode", scope_key="u1")
        results = await sem.retrieve("dark", scope_key="u1")
        assert len(results) == 1
        assert "dark" in results[0].content

    @pytest.mark.asyncio
    async def test_embedding_retrieve(self):
        sem = SemanticMemoryStore()
        await sem.store(
            "fact about python",
            scope_key="u1",
            metadata={"embedding": [1.0, 0.0]},
        )
        results = await sem.retrieve("x", scope_key="u1", query_embedding=[0.9, 0.1])
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_update_replaces_content(self):
        sem = SemanticMemoryStore()
        await sem.store("old fact", scope_key="u1")
        entries = await sem.retrieve("old", scope_key="u1")
        entry_id = entries[0].id

        await sem.update(entry_id, "new fact")
        results = await sem.retrieve("new", scope_key="u1")
        assert results[0].content == "new fact"

    @pytest.mark.asyncio
    async def test_no_max_entries_limit(self):
        sem = SemanticMemoryStore()
        for i in range(200):
            await sem.store(f"fact {i}", scope_key="u1")
        entries = await sem.retrieve("fact", scope_key="u1", top_k=200)
        assert len(entries) == 200


# ── EvictionJob ──────────────────────────────────────────────────────────────

class TestEvictionJob:
    @pytest.mark.asyncio
    async def test_high_importance_never_evicted(self):
        store = EpisodicMemoryStore()
        await store.store("critical preference", scope_key="u1", metadata={"importance": "high"})

        # Manually set created_at to 100 days ago
        import dataclasses
        bucket = store._store["u1"]
        for eid, e in bucket.items():
            bucket[eid] = dataclasses.replace(e, created_at=time.time() - 100 * 86400)

        job = EvictionJob(store)
        await job.run("u1")

        active = await store.get_all_active("u1")
        assert len(active) == 1

    @pytest.mark.asyncio
    async def test_low_importance_old_entry_archived(self):
        store = EpisodicMemoryStore()
        await store.store("temporary mention", scope_key="u1", metadata={"importance": "low"})

        import dataclasses
        bucket = store._store["u1"]
        for eid, e in bucket.items():
            bucket[eid] = dataclasses.replace(e, created_at=time.time() - 60 * 86400)

        job = EvictionJob(store)
        await job.run("u1")

        active = await store.get_all_active("u1")
        assert len(active) == 0  # archived or deleted


# ── DreamingConsolidator (no-LLM mode) ──────────────────────────────────────

class TestDreamingConsolidator:
    @pytest.mark.asyncio
    async def test_consolidates_entries_into_semantic(self):
        episodic = EpisodicMemoryStore()
        semantic = SemanticMemoryStore()
        dreamer = DreamingConsolidator(episodic, semantic)  # no LLM

        await episodic.store("user likes Python", scope_key="u1", metadata={"importance": "high"})
        await episodic.store("user prefers dark mode", scope_key="u1", metadata={"importance": "high"})

        await dreamer.run_cycle("u1")

        semantic_entries = await semantic.retrieve("user", scope_key="u1", top_k=10)
        assert len(semantic_entries) >= 1

        pending = await episodic.get_unconsolidated("u1")
        assert len(pending) == 0  # all marked consolidated

    @pytest.mark.asyncio
    async def test_skips_low_importance_singletons(self):
        episodic = EpisodicMemoryStore()
        semantic = SemanticMemoryStore()
        dreamer = DreamingConsolidator(episodic, semantic)

        await episodic.store("hmm interesting", scope_key="u1", metadata={"importance": "low"})

        await dreamer.run_cycle("u1")

        semantic_entries = await semantic.retrieve("hmm", scope_key="u1", top_k=10)
        assert len(semantic_entries) == 0

    @pytest.mark.asyncio
    async def test_dedup_prevents_duplicate_semantic(self):
        episodic = EpisodicMemoryStore()
        semantic = SemanticMemoryStore()
        dreamer = DreamingConsolidator(episodic, semantic)

        # Pre-populate semantic with the same content
        await semantic.store(
            "user likes Python",
            scope_key="u1",
            metadata={"embedding": [1.0, 0.0, 0.0]},
        )

        await episodic.store("user likes Python", scope_key="u1", metadata={"importance": "high"})

        # Inject matching embedding into episodic entry
        import dataclasses
        bucket = episodic._store["u1"]
        for eid, e in bucket.items():
            bucket[eid] = dataclasses.replace(e, embedding=[1.0, 0.0, 0.0])

        await dreamer.run_cycle("u1")

        # Should still be only 1 entry in semantic (dedup)
        results = await semantic.retrieve("Python", scope_key="u1", top_k=10)
        assert len(results) == 1
