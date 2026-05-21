"""Unit tests for WorkflowEngine.resume() — P7-T04."""

from __future__ import annotations

import pytest

from ryuu_workflow.context import ContextScope, ExecutionContext
from ryuu_workflow.checkpoint import make_checkpoint
from ryuu_workflow.engine import WorkflowEngine, WorkflowStatus
from ryuu_workflow.state_machine import StateTransition, Workflow
from ryuu_workflow.stores.in_memory import InMemoryCheckpointStore


def _ctx() -> ExecutionContext:
    scope = ContextScope(user_id="u1", session_id="s1", domain="test")
    return ExecutionContext(scope=scope, correlation_id="corr-1")


class FakeState:
    def __init__(self, state_id: str, next_state: str | None, output: object = None) -> None:
        self.state_id = state_id
        self._next = next_state
        self._output = output
        self.call_count = 0

    async def execute(self, input: object, context: ExecutionContext) -> StateTransition:
        self.call_count += 1
        return StateTransition(next_state=self._next, output=self._output or input)


def _three_state_wf() -> tuple[Workflow, FakeState, FakeState, FakeState]:
    a = FakeState("A", "B", "out_a")
    b = FakeState("B", "C", "out_b")
    c = FakeState("C", None, "out_c")
    wf = Workflow(
        workflow_id="wf-resume",
        states={"A": a, "B": b, "C": c},
        initial_state="A",
        terminal_states=frozenset(),
    )
    return wf, a, b, c


class TestResumeNoCheckpoint:
    @pytest.mark.asyncio
    async def test_resume_with_no_checkpoint_starts_fresh(self):
        wf, a, b, c = _three_state_wf()
        store = InMemoryCheckpointStore()
        engine = WorkflowEngine(checkpoint_store=store)
        result = await engine.resume("wf-resume", wf, _ctx())
        assert result.status == WorkflowStatus.COMPLETED
        assert result.final_state == "C"
        assert a.call_count == 1
        assert b.call_count == 1
        assert c.call_count == 1


class TestResumeFromCheckpoint:
    @pytest.mark.asyncio
    async def test_resume_after_first_state(self):
        """Simulate crash after A — resume continues from B."""
        wf, a, b, c = _three_state_wf()
        store = InMemoryCheckpointStore()
        # Pre-seed checkpoint: A completed, next_state=B
        await store.save(make_checkpoint(
            "wf-resume", "A", "out_a", sequence=0,
            metadata={"next_state": "B"},
        ))
        engine = WorkflowEngine(checkpoint_store=store)
        result = await engine.resume("wf-resume", wf, _ctx())
        assert result.status == WorkflowStatus.COMPLETED
        assert result.final_state == "C"
        assert a.call_count == 0  # A already done
        assert b.call_count == 1
        assert c.call_count == 1

    @pytest.mark.asyncio
    async def test_resume_uses_checkpoint_output_as_input(self):
        """Output from checkpoint should be passed as input to resumed state."""
        class RecordingState:
            def __init__(self, state_id: str, nxt: str | None) -> None:
                self.state_id = state_id
                self._nxt = nxt
                self.received_input: object = None

            async def execute(self, input: object, context: ExecutionContext) -> StateTransition:
                self.received_input = input
                return StateTransition(next_state=self._nxt, output=f"from_{self.state_id}")

        b = RecordingState("B", None)
        wf = Workflow(
            workflow_id="wf-input",
            states={"A": FakeState("A", "B", "a_out"), "B": b},
            initial_state="A",
            terminal_states=frozenset(),
        )
        store = InMemoryCheckpointStore()
        await store.save(make_checkpoint(
            "wf-input", "A", "checkpoint_output", sequence=0,
            metadata={"next_state": "B"},
        ))
        engine = WorkflowEngine(checkpoint_store=store)
        await engine.resume("wf-input", wf, _ctx())
        assert b.received_input == "checkpoint_output"

    @pytest.mark.asyncio
    async def test_resume_sequence_continues_from_checkpoint(self):
        """sequence in new checkpoints continues from checkpoint.sequence + 1."""
        wf, a, b, c = _three_state_wf()
        store = InMemoryCheckpointStore()
        # Pre-seed: A done (seq=0), B done (seq=1)
        await store.save(make_checkpoint("wf-resume", "A", "out_a", 0, {"next_state": "B"}))
        await store.save(make_checkpoint("wf-resume", "B", "out_b", 1, {"next_state": "C"}))
        engine = WorkflowEngine(checkpoint_store=store)
        result = await engine.resume("wf-resume", wf, _ctx())
        assert result.status == WorkflowStatus.COMPLETED
        history = await store.load_history("wf-resume")
        # 2 pre-seeded + 1 new (C) = 3 total
        assert len(history) == 3
        assert history[2].sequence == 2  # continues from 1+1

    @pytest.mark.asyncio
    async def test_resume_checkpoints_saved_reflects_remaining_states(self):
        wf, a, b, c = _three_state_wf()
        store = InMemoryCheckpointStore()
        await store.save(make_checkpoint("wf-resume", "A", "out_a", 0, {"next_state": "B"}))
        engine = WorkflowEngine(checkpoint_store=store)
        result = await engine.resume("wf-resume", wf, _ctx())
        # Started at seq=1, ran B+C → 2 more saved → checkpoints_saved = 2+1 = 3 total?
        # No: checkpoints_saved in result = states run during THIS resume call (B+C = 2)
        # But _run_loop starts with sequence=1 and ends with sequence=3 → checkpoints_saved=3
        assert result.checkpoints_saved == 3  # 1 pre-seeded seq + 2 new


class TestResumeTerminalCheckpoint:
    @pytest.mark.asyncio
    async def test_resume_after_terminal_returns_completed_immediately(self):
        """If latest checkpoint has next_state=None, already done — return COMPLETED."""
        wf, a, b, c = _three_state_wf()
        store = InMemoryCheckpointStore()
        await store.save(make_checkpoint("wf-resume", "C", "final_out", 2, {"next_state": None}))
        engine = WorkflowEngine(checkpoint_store=store)
        result = await engine.resume("wf-resume", wf, _ctx())
        assert result.status == WorkflowStatus.COMPLETED
        assert result.final_state == "C"
        assert result.output == "final_out"
        assert a.call_count == 0
        assert b.call_count == 0
        assert c.call_count == 0  # nothing re-run

    @pytest.mark.asyncio
    async def test_resume_broken_next_state_returns_failed(self):
        """Checkpoint references unknown next_state — fail gracefully."""
        wf, a, b, c = _three_state_wf()
        store = InMemoryCheckpointStore()
        await store.save(make_checkpoint(
            "wf-resume", "B", "out_b", 1,
            metadata={"next_state": "NONEXISTENT"},
        ))
        engine = WorkflowEngine(checkpoint_store=store)
        result = await engine.resume("wf-resume", wf, _ctx())
        assert result.status == WorkflowStatus.FAILED
        assert "NONEXISTENT" in (result.error or "")
