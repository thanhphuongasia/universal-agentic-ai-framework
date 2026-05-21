"""Parametric contract tests for ICheckpointStore + IWorkflowEngine — P7-T06."""

from __future__ import annotations

import pytest

from ryuu_workflow.errors import FatalError
from ryuu_workflow.context import ContextScope, ExecutionContext
from ryuu_workflow.checkpoint import ICheckpointStore, make_checkpoint
from ryuu_workflow.engine import IWorkflowEngine, WorkflowEngine, WorkflowStatus
from ryuu_workflow.state_machine import StateTransition, Workflow
from ryuu_workflow.stores.file import FileCheckpointStore
from ryuu_workflow.stores.in_memory import InMemoryCheckpointStore


def _ctx() -> ExecutionContext:
    scope = ContextScope(user_id="u1", session_id="s1", domain="contract")
    return ExecutionContext(scope=scope, correlation_id="c-test")


@pytest.fixture(params=["in_memory", "file"])
def checkpoint_store(request, tmp_path) -> ICheckpointStore:
    if request.param == "in_memory":
        return InMemoryCheckpointStore()
    return FileCheckpointStore(tmp_path)


@pytest.fixture
def engine(checkpoint_store: ICheckpointStore) -> WorkflowEngine:
    return WorkflowEngine(checkpoint_store=checkpoint_store)


class FakeState:
    def __init__(self, state_id: str, next_state: str | None, output: object = None) -> None:
        self.state_id = state_id
        self._next = next_state
        self._output = output

    async def execute(self, input: object, context: ExecutionContext) -> StateTransition:
        return StateTransition(next_state=self._next, output=self._output or input)


class FakeFatalState:
    def __init__(self, state_id: str) -> None:
        self.state_id = state_id

    async def execute(self, input: object, context: ExecutionContext) -> StateTransition:
        raise FatalError("boom")


def _simple_wf() -> Workflow:
    a = FakeState("A", "B", "out_a")
    b = FakeState("B", "C", "out_b")
    c = FakeState("C", None, "out_c")
    return Workflow(
        workflow_id="wf-contract",
        states={"A": a, "B": b, "C": c},
        initial_state="A",
        terminal_states=frozenset(),
    )


class TestCheckpointStoreContract:
    @pytest.mark.asyncio
    async def test_save_then_load_latest_returns_saved(self, checkpoint_store):
        cp = make_checkpoint("wf1", "PARSE", {"x": 1}, 0)
        await checkpoint_store.save(cp)
        loaded = await checkpoint_store.load_latest("wf1")
        assert loaded is not None
        assert loaded.state_id == "PARSE"
        assert loaded.sequence == 0

    @pytest.mark.asyncio
    async def test_load_latest_on_empty_returns_none(self, checkpoint_store):
        assert await checkpoint_store.load_latest("nonexistent") is None

    @pytest.mark.asyncio
    async def test_load_history_ordered_by_sequence(self, checkpoint_store):
        await checkpoint_store.save(make_checkpoint("wf2", "C", None, 2))
        await checkpoint_store.save(make_checkpoint("wf2", "A", None, 0))
        await checkpoint_store.save(make_checkpoint("wf2", "B", None, 1))
        history = await checkpoint_store.load_history("wf2")
        assert [c.sequence for c in history] == [0, 1, 2]

    @pytest.mark.asyncio
    async def test_delete_idempotent(self, checkpoint_store):
        await checkpoint_store.save(make_checkpoint("wf3", "X", None, 0))
        await checkpoint_store.delete("wf3")
        await checkpoint_store.delete("wf3")  # must not raise
        assert await checkpoint_store.load_latest("wf3") is None

    @pytest.mark.asyncio
    async def test_isolation_between_workflow_ids(self, checkpoint_store):
        await checkpoint_store.save(make_checkpoint("wf-a", "X", "alpha", 0))
        await checkpoint_store.save(make_checkpoint("wf-b", "X", "beta", 0))
        a = await checkpoint_store.load_latest("wf-a")
        b = await checkpoint_store.load_latest("wf-b")
        assert a is not None and a.output == "alpha"
        assert b is not None and b.output == "beta"

    def test_isinstance_protocol(self, checkpoint_store):
        assert isinstance(checkpoint_store, ICheckpointStore)


class TestWorkflowEngineContract:
    @pytest.mark.asyncio
    async def test_run_completes_simple_3_state_workflow(self, engine):
        result = await engine.run(_simple_wf(), "start", _ctx())
        assert result.status == WorkflowStatus.COMPLETED
        assert result.final_state == "C"
        assert result.checkpoints_saved == 3

    @pytest.mark.asyncio
    async def test_resume_after_partial_run_completes(self, engine, checkpoint_store):
        wf = _simple_wf()
        # Pre-seed: A done, next=B
        await checkpoint_store.save(
            make_checkpoint("wf-contract", "A", "out_a", 0, {"next_state": "B"})
        )
        result = await engine.resume("wf-contract", wf, _ctx())
        assert result.status == WorkflowStatus.COMPLETED
        assert result.checkpoints_saved == 3  # 1 pre-seeded + 2 new

    @pytest.mark.asyncio
    async def test_fatal_error_results_in_failed_status(self, engine):
        fatal = FakeFatalState("X")
        wf = Workflow(
            workflow_id="wf-fatal",
            states={"X": fatal},
            initial_state="X",
            terminal_states=frozenset(),
        )
        result = await engine.run(wf, None, _ctx())
        assert result.status == WorkflowStatus.FAILED
        assert result.error == "boom"

    def test_isinstance_protocol(self, engine):
        assert isinstance(engine, IWorkflowEngine)
