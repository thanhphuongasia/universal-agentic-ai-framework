"""Integration smoke test — Phase 7 Workflow Engine. P7-T08.

Tests:
1. Full 3-state workflow PARSE → ENRICH → DERIVE completes.
2. SIGKILL simulation: engine A runs 1 state, crashes, engine B resumes → completes.
3. Public API imports work from ryuu top-level.
"""

from __future__ import annotations

import pytest

from ryuu_workflow.context import ContextScope, ExecutionContext
from ryuu_workflow.checkpoint import make_checkpoint
from ryuu_workflow.engine import WorkflowEngine, WorkflowStatus
from ryuu_workflow.state_machine import StateTransition, Workflow
from ryuu_workflow.stores.file import FileCheckpointStore
from ryuu_workflow.stores.in_memory import InMemoryCheckpointStore


def _ctx() -> ExecutionContext:
    scope = ContextScope(user_id="smoke", session_id="s1", domain="integration")
    return ExecutionContext(scope=scope, correlation_id="smoke-test")


class ParseState:
    state_id = "PARSE"

    async def execute(self, input: object, context: ExecutionContext) -> StateTransition:
        return StateTransition(next_state="ENRICH", output={"parsed": str(input)})


class EnrichState:
    state_id = "ENRICH"

    async def execute(self, input: object, context: ExecutionContext) -> StateTransition:
        assert isinstance(input, dict)
        return StateTransition(next_state="DERIVE", output={**input, "enriched": True})


class DeriveState:
    state_id = "DERIVE"

    async def execute(self, input: object, context: ExecutionContext) -> StateTransition:
        assert isinstance(input, dict)
        return StateTransition(next_state=None, output={**input, "derived": True})


def _pipeline_workflow() -> Workflow:
    return Workflow(
        workflow_id="pipeline-smoke",
        states={
            "PARSE": ParseState(),
            "ENRICH": EnrichState(),
            "DERIVE": DeriveState(),
        },
        initial_state="PARSE",
        terminal_states=frozenset(),
    )


class TestFullWorkflowRun:
    @pytest.mark.asyncio
    async def test_3_state_pipeline_completes(self):
        store = InMemoryCheckpointStore()
        engine = WorkflowEngine(checkpoint_store=store)
        result = await engine.run(_pipeline_workflow(), "raw_document", _ctx())

        assert result.status == WorkflowStatus.COMPLETED
        assert result.final_state == "DERIVE"
        assert result.checkpoints_saved == 3
        assert result.output == {"parsed": "raw_document", "enriched": True, "derived": True}

    @pytest.mark.asyncio
    async def test_checkpoints_saved_for_all_states(self):
        store = InMemoryCheckpointStore()
        engine = WorkflowEngine(checkpoint_store=store)
        await engine.run(_pipeline_workflow(), "doc", _ctx())

        history = await store.load_history("pipeline-smoke")
        assert len(history) == 3
        assert history[0].state_id == "PARSE"
        assert history[1].state_id == "ENRICH"
        assert history[2].state_id == "DERIVE"


class TestSigkillSimulation:
    @pytest.mark.asyncio
    async def test_resume_after_first_state_crash(self, tmp_path):
        """Engine A completes PARSE only (simulated crash), Engine B resumes → full completion."""
        wf_id = "pipeline-sigkill"
        wf = Workflow(
            workflow_id=wf_id,
            states={
                "PARSE": ParseState(),
                "ENRICH": EnrichState(),
                "DERIVE": DeriveState(),
            },
            initial_state="PARSE",
            terminal_states=frozenset(),
        )

        store_a = FileCheckpointStore(tmp_path)
        # Simulate: PARSE completed, crash before ENRICH
        await store_a.save(make_checkpoint(
            wf_id, "PARSE",
            {"parsed": "raw_document"},
            sequence=0,
            metadata={"next_state": "ENRICH"},
        ))

        # Engine B: fresh instance, same store, resume
        store_b = FileCheckpointStore(tmp_path)
        engine_b = WorkflowEngine(checkpoint_store=store_b)
        result = await engine_b.resume(wf_id, wf, _ctx())

        assert result.status == WorkflowStatus.COMPLETED
        assert result.final_state == "DERIVE"
        # B ran ENRICH (seq=1) + DERIVE (seq=2) → 3 total in store
        history = await store_b.load_history(wf_id)
        assert len(history) == 3

    @pytest.mark.asyncio
    async def test_resume_after_two_state_crash(self, tmp_path):
        """Crash after PARSE + ENRICH → resume only runs DERIVE."""
        wf_id = "pipeline-2crash"
        wf = Workflow(
            workflow_id=wf_id,
            states={
                "PARSE": ParseState(),
                "ENRICH": EnrichState(),
                "DERIVE": DeriveState(),
            },
            initial_state="PARSE",
            terminal_states=frozenset(),
        )
        store = FileCheckpointStore(tmp_path)
        await store.save(make_checkpoint(
            wf_id, "PARSE", {"parsed": "doc"}, 0, {"next_state": "ENRICH"}
        ))
        await store.save(make_checkpoint(
            wf_id, "ENRICH", {"parsed": "doc", "enriched": True}, 1, {"next_state": "DERIVE"}
        ))

        engine = WorkflowEngine(checkpoint_store=store)
        result = await engine.resume(wf_id, wf, _ctx())

        assert result.status == WorkflowStatus.COMPLETED
        assert result.output == {"parsed": "doc", "enriched": True, "derived": True}


class TestPublicAPIImports:
    def test_workflow_engine_importable_from_ryuu_workflow(self):
        from ryuu_workflow import WorkflowEngine  # noqa: F401

    def test_workflow_importable_from_ryuu_workflow(self):
        from ryuu_workflow import Workflow  # noqa: F401

    def test_istate_importable_from_ryuu_workflow(self):
        from ryuu_workflow import IState  # noqa: F401

    def test_icheckpointstore_importable_from_ryuu_workflow(self):
        from ryuu_workflow import ICheckpointStore  # noqa: F401

    def test_filecheckpointstore_importable_from_ryuu_workflow(self):
        from ryuu_workflow import FileCheckpointStore  # noqa: F401

    def test_version_bumped(self):
        import ryuu
        assert ryuu.__version__ == "0.3.0a15"  # Phase 11.y output_schema= + strict mode
