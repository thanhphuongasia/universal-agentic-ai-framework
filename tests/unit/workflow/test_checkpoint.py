"""Unit tests for ICheckpointStore + Checkpoint + InMemoryCheckpointStore — P7-T01."""

from __future__ import annotations

import pytest

from uaaf_workflow.checkpoint import Checkpoint, ICheckpointStore, make_checkpoint
from uaaf_workflow.stores.in_memory import InMemoryCheckpointStore


def _cp(workflow_id: str, state_id: str, output: object, sequence: int) -> Checkpoint:
    return make_checkpoint(workflow_id, state_id, output, sequence)


class TestCheckpointDataclass:
    def test_frozen(self):
        cp = _cp("wf1", "PARSE", {"data": 1}, 0)
        with pytest.raises((AttributeError, TypeError)):
            cp.sequence = 99  # type: ignore[misc]

    def test_default_metadata_empty(self):
        cp = _cp("wf1", "PARSE", None, 0)
        assert cp.metadata == {}

    def test_metadata_custom(self):
        cp = make_checkpoint("wf1", "PARSE", None, 0, metadata={"next": "ENRICH"})
        assert cp.metadata["next"] == "ENRICH"


class TestInMemoryCheckpointStore:
    @pytest.mark.asyncio
    async def test_save_and_load_latest(self):
        store = InMemoryCheckpointStore()
        cp = _cp("wf1", "PARSE", {"result": "parsed"}, 0)
        await store.save(cp)
        loaded = await store.load_latest("wf1")
        assert loaded == cp

    @pytest.mark.asyncio
    async def test_load_latest_returns_highest_sequence(self):
        store = InMemoryCheckpointStore()
        cp0 = _cp("wf1", "PARSE", "out0", 0)
        cp1 = _cp("wf1", "ENRICH", "out1", 1)
        cp2 = _cp("wf1", "DERIVE", "out2", 2)
        await store.save(cp0)
        await store.save(cp2)  # out of order
        await store.save(cp1)
        latest = await store.load_latest("wf1")
        assert latest is not None
        assert latest.sequence == 2

    @pytest.mark.asyncio
    async def test_load_latest_nonexistent_returns_none(self):
        store = InMemoryCheckpointStore()
        result = await store.load_latest("nonexistent_workflow")
        assert result is None

    @pytest.mark.asyncio
    async def test_load_history_ordered_ascending(self):
        store = InMemoryCheckpointStore()
        cp0 = _cp("wf1", "A", None, 0)
        cp1 = _cp("wf1", "B", None, 1)
        cp2 = _cp("wf1", "C", None, 2)
        await store.save(cp2)
        await store.save(cp0)
        await store.save(cp1)
        history = await store.load_history("wf1")
        assert [c.sequence for c in history] == [0, 1, 2]

    @pytest.mark.asyncio
    async def test_load_history_empty_returns_empty_list(self):
        store = InMemoryCheckpointStore()
        history = await store.load_history("wf_unknown")
        assert history == []

    @pytest.mark.asyncio
    async def test_delete_clears_workflow(self):
        store = InMemoryCheckpointStore()
        await store.save(_cp("wf1", "A", None, 0))
        await store.delete("wf1")
        assert await store.load_latest("wf1") is None
        assert await store.load_history("wf1") == []

    @pytest.mark.asyncio
    async def test_delete_idempotent(self):
        store = InMemoryCheckpointStore()
        await store.delete("wf_never_existed")  # must not raise
        await store.delete("wf_never_existed")

    @pytest.mark.asyncio
    async def test_isolation_between_workflow_ids(self):
        store = InMemoryCheckpointStore()
        await store.save(_cp("wf1", "PARSE", "data1", 0))
        await store.save(_cp("wf2", "PARSE", "data2", 0))
        latest1 = await store.load_latest("wf1")
        latest2 = await store.load_latest("wf2")
        assert latest1 is not None and latest1.output == "data1"
        assert latest2 is not None and latest2.output == "data2"

    def test_isinstance_protocol(self):
        store = InMemoryCheckpointStore()
        assert isinstance(store, ICheckpointStore)
