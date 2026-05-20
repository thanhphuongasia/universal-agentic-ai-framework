"""Unit tests for WorkflowEngine.run() — P7-T03."""

from __future__ import annotations

import pytest

from uaaf_workflow.errors import DegradedError, FatalError, RetryableError
from uaaf_workflow.context import ContextScope, ExecutionContext
from uaaf_workflow.engine import IWorkflowEngine, WorkflowEngine, WorkflowResult, WorkflowStatus
from uaaf_workflow.state_machine import IState, StateTransition, Workflow
from uaaf_workflow.stores.in_memory import InMemoryCheckpointStore


def _ctx() -> ExecutionContext:
    scope = ContextScope(user_id="u1", session_id="s1", domain="test")
    return ExecutionContext(scope=scope, correlation_id="corr-1")


class FakeState:
    def __init__(
        self,
        state_id: str,
        next_state: str | None,
        output: object = None,
        raises: Exception | None = None,
        raises_on_attempt: int | None = None,
    ) -> None:
        self.state_id = state_id
        self._next = next_state
        self._output = output
        self._raises = raises
        self._raises_on_attempt = raises_on_attempt
        self.call_count = 0

    async def execute(self, input: object, context: ExecutionContext) -> StateTransition:
        attempt = self.call_count
        self.call_count += 1
        if self._raises is not None:
            if self._raises_on_attempt is None or attempt == self._raises_on_attempt:
                raise self._raises
        return StateTransition(next_state=self._next, output=self._output or input)


def _make_workflow(
    states_spec: list[tuple[str, str | None, object]],
    explicit_terminal: set[str] | None = None,
) -> Workflow:
    """Build a Workflow from (state_id, next_state, output) triples.

    States returning next_state=None terminate naturally (still run + checkpointed).
    explicit_terminal contains states that are end-markers and are never executed.
    """
    states: dict[str, IState] = {}
    for sid, nxt, out in states_spec:
        states[sid] = FakeState(sid, nxt, out)
    first = states_spec[0][0]
    return Workflow(
        workflow_id="wf-test",
        states=states,
        initial_state=first,
        terminal_states=frozenset(explicit_terminal or set()),
    )


def _engine(retries: int = 3, max_t: int = 1000) -> WorkflowEngine:
    return WorkflowEngine(
        checkpoint_store=InMemoryCheckpointStore(),
        max_state_retries=retries,
        max_transitions=max_t,
    )


class TestWorkflowEngineHappyPath:
    @pytest.mark.asyncio
    async def test_3_state_workflow_completes(self):
        # C returns next_state=None — all 3 states are run, C is not in terminal_states
        wf = _make_workflow([("A", "B", "out_a"), ("B", "C", "out_b"), ("C", None, "out_c")])
        engine = _engine()
        result = await engine.run(wf, "start", _ctx())
        assert result.status == WorkflowStatus.COMPLETED
        assert result.final_state == "C"
        assert result.output == "out_c"

    @pytest.mark.asyncio
    async def test_checkpoints_saved_equals_states_run(self):
        wf = _make_workflow([("A", "B", "a"), ("B", "C", "b"), ("C", None, "c")])
        store = InMemoryCheckpointStore()
        engine = WorkflowEngine(checkpoint_store=store)
        result = await engine.run(wf, "start", _ctx())
        assert result.checkpoints_saved == 3
        history = await store.load_history("wf-test")
        assert len(history) == 3

    @pytest.mark.asyncio
    async def test_checkpoint_metadata_has_next_state(self):
        wf = _make_workflow([("A", "B", "a"), ("B", None, "b")])
        store = InMemoryCheckpointStore()
        engine = WorkflowEngine(checkpoint_store=store)
        await engine.run(wf, "start", _ctx())
        history = await store.load_history("wf-test")
        assert history[0].metadata["next_state"] == "B"
        assert history[1].metadata["next_state"] is None  # last state returns None

    @pytest.mark.asyncio
    async def test_explicit_terminal_as_initial_state_completes_immediately(self):
        """If initial_state is in terminal_states, no states run and 0 checkpoints saved."""
        a = FakeState("A", next_state=None, output="done")
        wf = Workflow(
            workflow_id="wf-instant",
            states={"A": a},
            initial_state="A",
            terminal_states=frozenset({"A"}),
        )
        engine = _engine()
        result = await engine.run(wf, "start", _ctx())
        assert result.status == WorkflowStatus.COMPLETED
        assert result.final_state == "A"
        assert result.checkpoints_saved == 0  # explicit terminal: never run

    @pytest.mark.asyncio
    async def test_output_passed_between_states(self):
        class PassThrough:
            def __init__(self, sid: str, nxt: str | None) -> None:
                self.state_id = sid
                self._nxt = nxt
                self.received_input: object = None

            async def execute(self, input: object, context: ExecutionContext) -> StateTransition:
                self.received_input = input
                return StateTransition(next_state=self._nxt, output=f"processed_{input}")

        a = PassThrough("A", "B")
        b = PassThrough("B", None)
        wf = Workflow(
            workflow_id="wf-pass",
            states={"A": a, "B": b},
            initial_state="A",
            terminal_states=frozenset(),  # B terminates naturally via next_state=None
        )
        engine = _engine()
        await engine.run(wf, "raw_input", _ctx())
        assert a.received_input == "raw_input"
        assert b.received_input == "processed_raw_input"


class TestWorkflowEngineErrorHandling:
    @pytest.mark.asyncio
    async def test_retryable_error_then_success(self):
        """State fails once with RetryableError then succeeds."""
        a = FakeState(
            "A", next_state="B", output="a_ok",
            raises=RetryableError("transient"), raises_on_attempt=0,
        )
        b = FakeState("B", next_state=None, output="done")
        wf = Workflow(
            workflow_id="wf-retry",
            states={"A": a, "B": b},
            initial_state="A",
            terminal_states=frozenset({"B"}),
        )
        engine = WorkflowEngine(
            checkpoint_store=InMemoryCheckpointStore(),
            max_state_retries=3,
        )
        result = await engine.run(wf, "start", _ctx())
        assert result.status == WorkflowStatus.COMPLETED
        assert a.call_count == 2  # failed once, succeeded once

    @pytest.mark.asyncio
    async def test_retryable_error_exhausted_returns_failed(self):
        # A always raises; without natural termination, engine should fail after max_retries
        a = FakeState("A", next_state=None, raises=RetryableError("always fails"))
        wf = Workflow(
            workflow_id="wf-exhaust",
            states={"A": a},
            initial_state="A",
            terminal_states=frozenset(),  # A not terminal — runs until exhausted
        )
        engine = WorkflowEngine(
            checkpoint_store=InMemoryCheckpointStore(),
            max_state_retries=2,
        )
        result = await engine.run(wf, "start", _ctx())
        assert result.status == WorkflowStatus.FAILED
        assert "max retries" in (result.error or "")
        assert a.call_count == 2

    @pytest.mark.asyncio
    async def test_fatal_error_stops_immediately(self):
        a = FakeState("A", next_state=None, raises=FatalError("unrecoverable"))
        wf = Workflow(
            workflow_id="wf-fatal",
            states={"A": a},
            initial_state="A",
            terminal_states=frozenset(),
        )
        engine = WorkflowEngine(
            checkpoint_store=InMemoryCheckpointStore(),
            max_state_retries=3,
        )
        result = await engine.run(wf, "start", _ctx())
        assert result.status == WorkflowStatus.FAILED
        assert result.error == "unrecoverable"
        assert a.call_count == 1  # no retry

    @pytest.mark.asyncio
    async def test_degraded_error_no_retry_returns_failed_gracefully(self):
        """DegradedError: no retry, returns FAILED gracefully (no exception raised)."""
        a = FakeState("A", next_state=None, raises=DegradedError("degraded"))
        wf = Workflow(
            workflow_id="wf-degraded",
            states={"A": a},
            initial_state="A",
            terminal_states=frozenset(),
        )
        engine = WorkflowEngine(
            checkpoint_store=InMemoryCheckpointStore(),
            max_state_retries=3,
        )
        result = await engine.run(wf, "start", _ctx())
        assert result.status == WorkflowStatus.FAILED
        assert a.call_count == 1  # no retry — immediate break

    @pytest.mark.asyncio
    async def test_max_transitions_cap(self):
        """Cyclic workflow hits max_transitions and returns FAILED."""
        a = FakeState("A", next_state="B", output="a")
        b = FakeState("B", next_state="A", output="b")
        wf = Workflow(
            workflow_id="wf-cycle",
            states={"A": a, "B": b},
            initial_state="A",
            terminal_states=frozenset(),
        )
        engine = WorkflowEngine(
            checkpoint_store=InMemoryCheckpointStore(),
            max_transitions=4,
        )
        result = await engine.run(wf, "start", _ctx())
        assert result.status == WorkflowStatus.FAILED
        assert "max transitions" in (result.error or "")


class TestWorkflowEngineProtocol:
    def test_isinstance_protocol(self):
        engine = _engine()
        assert isinstance(engine, IWorkflowEngine)

    @pytest.mark.asyncio
    async def test_run_does_not_raise_on_fatal_error(self):
        """Engine must return WorkflowResult, never propagate exceptions."""
        a = FakeState("A", next_state=None, raises=FatalError("boom"))
        wf = Workflow(
            workflow_id="wf-no-raise",
            states={"A": a},
            initial_state="A",
            terminal_states=frozenset(),
        )
        result = await _engine().run(wf, None, _ctx())
        assert isinstance(result, WorkflowResult)
