"""Unit tests for FakeCheckpointStore + FakeWorkflowEngine — P7-T07."""

from __future__ import annotations

import pytest

from uaaf._testing.fakes import FakeCheckpointStore, FakeWorkflowEngine
from uaaf_workflow.context import ContextScope, ExecutionContext
from uaaf_workflow.checkpoint import ICheckpointStore, make_checkpoint
from uaaf_workflow.engine import IWorkflowEngine, WorkflowResult, WorkflowStatus
from uaaf_workflow.state_machine import Workflow


def _ctx() -> ExecutionContext:
    scope = ContextScope(user_id="u1", session_id="s1", domain="test")
    return ExecutionContext(scope=scope, correlation_id="corr-1")


def _wf() -> Workflow:
    return Workflow(
        workflow_id="wf-fake",
        states={},
        initial_state="A",
        terminal_states=frozenset({"A"}),
    )


class TestFakeCheckpointStore:
    def test_isinstance_protocol(self):
        assert isinstance(FakeCheckpointStore(), ICheckpointStore)

    @pytest.mark.asyncio
    async def test_save_increments_counter(self):
        store = FakeCheckpointStore()
        await store.save(make_checkpoint("wf1", "A", None, 0))
        await store.save(make_checkpoint("wf1", "B", None, 1))
        assert store.save_count == 2

    @pytest.mark.asyncio
    async def test_load_latest_increments_counter(self):
        store = FakeCheckpointStore()
        await store.load_latest("wf1")
        await store.load_latest("wf1")
        assert store.load_count == 2

    @pytest.mark.asyncio
    async def test_save_and_load_latest(self):
        store = FakeCheckpointStore()
        cp = make_checkpoint("wf1", "PARSE", "data", 0)
        await store.save(cp)
        loaded = await store.load_latest("wf1")
        assert loaded is not None
        assert loaded.state_id == "PARSE"

    @pytest.mark.asyncio
    async def test_load_history_ordered(self):
        store = FakeCheckpointStore()
        await store.save(make_checkpoint("wf1", "C", None, 2))
        await store.save(make_checkpoint("wf1", "A", None, 0))
        await store.save(make_checkpoint("wf1", "B", None, 1))
        history = await store.load_history("wf1")
        assert [c.sequence for c in history] == [0, 1, 2]

    @pytest.mark.asyncio
    async def test_delete_clears_data(self):
        store = FakeCheckpointStore()
        await store.save(make_checkpoint("wf1", "A", None, 0))
        await store.delete("wf1")
        assert await store.load_latest("wf1") is None


class TestFakeWorkflowEngine:
    def test_isinstance_protocol(self):
        assert isinstance(FakeWorkflowEngine(), IWorkflowEngine)

    @pytest.mark.asyncio
    async def test_run_returns_default_completed(self):
        engine = FakeWorkflowEngine()
        result = await engine.run(_wf(), None, _ctx())
        assert result.status == WorkflowStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_run_returns_canned_result(self):
        canned = WorkflowResult(
            workflow_id="wf-fake",
            status=WorkflowStatus.FAILED,
            final_state="X",
            output="err",
            error="planned failure",
        )
        engine = FakeWorkflowEngine(results=[canned])
        result = await engine.run(_wf(), None, _ctx())
        assert result.status == WorkflowStatus.FAILED
        assert result.error == "planned failure"

    @pytest.mark.asyncio
    async def test_run_count_tracked(self):
        engine = FakeWorkflowEngine()
        await engine.run(_wf(), None, _ctx())
        await engine.run(_wf(), None, _ctx())
        assert engine.run_count == 2

    @pytest.mark.asyncio
    async def test_resume_count_tracked(self):
        engine = FakeWorkflowEngine()
        await engine.resume("wf-fake", _wf(), _ctx())
        assert engine.resume_count == 1

    @pytest.mark.asyncio
    async def test_canned_results_consumed_in_order(self):
        r1 = WorkflowResult("wf", WorkflowStatus.COMPLETED, "A", "out1")
        r2 = WorkflowResult("wf", WorkflowStatus.FAILED, None, None, error="oops")
        engine = FakeWorkflowEngine(results=[r1, r2])
        res1 = await engine.run(_wf(), None, _ctx())
        res2 = await engine.run(_wf(), None, _ctx())
        assert res1.output == "out1"
        assert res2.status == WorkflowStatus.FAILED
