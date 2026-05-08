"""Unit tests for FileCheckpointStore — P7-T05."""

from __future__ import annotations

import pytest

from uaaf.observability.errors import FatalError
from uaaf.workflow.checkpoint import ICheckpointStore, make_checkpoint
from uaaf.workflow.stores.file import FileCheckpointStore


class TestFileCheckpointStoreBasic:
    @pytest.mark.asyncio
    async def test_save_and_load_latest(self, tmp_path):
        store = FileCheckpointStore(tmp_path)
        cp = make_checkpoint("wf1", "PARSE", {"result": "ok"}, sequence=0)
        await store.save(cp)
        loaded = await store.load_latest("wf1")
        assert loaded is not None
        assert loaded.state_id == "PARSE"
        assert loaded.output == {"result": "ok"}
        assert loaded.sequence == 0

    @pytest.mark.asyncio
    async def test_load_latest_returns_highest_sequence(self, tmp_path):
        store = FileCheckpointStore(tmp_path)
        await store.save(make_checkpoint("wf1", "A", "out0", 0))
        await store.save(make_checkpoint("wf1", "C", "out2", 2))
        await store.save(make_checkpoint("wf1", "B", "out1", 1))
        latest = await store.load_latest("wf1")
        assert latest is not None
        assert latest.sequence == 2

    @pytest.mark.asyncio
    async def test_load_latest_nonexistent_returns_none(self, tmp_path):
        store = FileCheckpointStore(tmp_path)
        result = await store.load_latest("wf_unknown")
        assert result is None

    @pytest.mark.asyncio
    async def test_load_history_ordered_ascending(self, tmp_path):
        store = FileCheckpointStore(tmp_path)
        await store.save(make_checkpoint("wf1", "C", None, 2))
        await store.save(make_checkpoint("wf1", "A", None, 0))
        await store.save(make_checkpoint("wf1", "B", None, 1))
        history = await store.load_history("wf1")
        assert [c.sequence for c in history] == [0, 1, 2]

    @pytest.mark.asyncio
    async def test_load_history_empty_returns_empty(self, tmp_path):
        store = FileCheckpointStore(tmp_path)
        assert await store.load_history("wf_none") == []

    @pytest.mark.asyncio
    async def test_delete_clears_workflow(self, tmp_path):
        store = FileCheckpointStore(tmp_path)
        await store.save(make_checkpoint("wf1", "A", None, 0))
        await store.delete("wf1")
        assert await store.load_latest("wf1") is None

    @pytest.mark.asyncio
    async def test_delete_idempotent(self, tmp_path):
        store = FileCheckpointStore(tmp_path)
        await store.delete("wf_never_existed")  # must not raise
        await store.delete("wf_never_existed")


class TestFileCheckpointStoreRoundTrip:
    @pytest.mark.asyncio
    async def test_round_trip_preserves_all_fields(self, tmp_path):
        store = FileCheckpointStore(tmp_path)
        cp = make_checkpoint(
            "wf-rt", "ENRICH", {"items": [1, 2, 3], "flag": True},
            sequence=5, metadata={"next_state": "DERIVE"},
        )
        await store.save(cp)
        loaded = await store.load_latest("wf-rt")
        assert loaded is not None
        assert loaded.workflow_id == cp.workflow_id
        assert loaded.state_id == cp.state_id
        assert loaded.output == cp.output
        assert loaded.sequence == cp.sequence
        assert loaded.metadata == cp.metadata

    @pytest.mark.asyncio
    async def test_cross_process_simulation(self, tmp_path):
        """store A saves; store B (fresh instance, same base_dir) loads — result matches."""
        store_a = FileCheckpointStore(tmp_path)
        await store_a.save(make_checkpoint("wf-cp", "PARSE", "payload", 0))
        store_b = FileCheckpointStore(tmp_path)  # fresh instance
        loaded = await store_b.load_latest("wf-cp")
        assert loaded is not None
        assert loaded.output == "payload"


class TestFileCheckpointStoreErrors:
    @pytest.mark.asyncio
    async def test_non_serializable_output_raises_fatal(self, tmp_path):
        store = FileCheckpointStore(tmp_path)

        class NotSerializable:
            pass

        cp = make_checkpoint("wf1", "A", NotSerializable(), 0)
        with pytest.raises(FatalError, match="JSON-serializable"):
            await store.save(cp)

    @pytest.mark.asyncio
    async def test_isolation_between_workflows(self, tmp_path):
        store = FileCheckpointStore(tmp_path)
        await store.save(make_checkpoint("wf1", "A", "data1", 0))
        await store.save(make_checkpoint("wf2", "A", "data2", 0))
        assert (await store.load_latest("wf1")).output == "data1"  # type: ignore[union-attr]
        assert (await store.load_latest("wf2")).output == "data2"  # type: ignore[union-attr]


class TestFileCheckpointStoreProtocol:
    def test_isinstance_protocol(self, tmp_path):
        store = FileCheckpointStore(tmp_path)
        assert isinstance(store, ICheckpointStore)
