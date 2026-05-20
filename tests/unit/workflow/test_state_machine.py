"""Unit tests for IState + Workflow + StateMachine — P7-T02."""

from __future__ import annotations

import pytest

from uaaf_workflow.errors import FatalError
from uaaf_workflow.context import ContextScope, ExecutionContext
from uaaf_workflow.state_machine import (
    IState,
    StateMachine,
    StateTransition,
    Workflow,
)


def _ctx() -> ExecutionContext:
    scope = ContextScope(user_id="u1", session_id="s1", domain="test")
    return ExecutionContext(scope=scope, correlation_id="corr-1")


class FakeState:
    """A configurable IState implementation for testing."""

    def __init__(self, state_id: str, next_state: str | None, output: object = None) -> None:
        self.state_id = state_id
        self._next = next_state
        self._output = output
        self.call_count = 0

    async def execute(self, input: object, context: ExecutionContext) -> StateTransition:
        self.call_count += 1
        return StateTransition(next_state=self._next, output=self._output or input)


def _three_state_workflow() -> Workflow:
    """A→B→C where C is terminal."""
    a = FakeState("A", next_state="B", output="from_A")
    b = FakeState("B", next_state="C", output="from_B")
    c = FakeState("C", next_state=None, output="from_C")
    return Workflow(
        workflow_id="wf-test",
        states={"A": a, "B": b, "C": c},
        initial_state="A",
        terminal_states=frozenset({"C"}),
    )


class TestWorkflowDataclass:
    def test_frozen(self):
        wf = _three_state_workflow()
        with pytest.raises((AttributeError, TypeError)):
            wf.workflow_id = "other"  # type: ignore[misc]

    def test_fields(self):
        wf = _three_state_workflow()
        assert wf.workflow_id == "wf-test"
        assert wf.initial_state == "A"
        assert "C" in wf.terminal_states


class TestStateMachineValidate:
    def test_validate_valid_workflow(self):
        sm = StateMachine(_three_state_workflow())
        sm.validate()  # must not raise

    def test_validate_missing_initial_state(self):
        wf = Workflow(
            workflow_id="wf",
            states={},
            initial_state="MISSING",
            terminal_states=frozenset(),
        )
        with pytest.raises(FatalError, match="initial_state"):
            StateMachine(wf).validate()

    def test_validate_key_mismatch(self):
        bad = FakeState("WRONG_ID", next_state=None)
        wf = Workflow(
            workflow_id="wf",
            states={"CORRECT_KEY": bad},
            initial_state="CORRECT_KEY",
            terminal_states=frozenset({"CORRECT_KEY"}),
        )
        with pytest.raises(FatalError, match="WRONG_ID"):
            StateMachine(wf).validate()


class TestStateMachineStep:
    @pytest.mark.asyncio
    async def test_step_dispatches_to_correct_state(self):
        wf = _three_state_workflow()
        sm = StateMachine(wf)
        ctx = _ctx()
        transition = await sm.step("A", "initial_input", ctx)
        assert transition.next_state == "B"
        assert transition.output == "from_A"
        assert wf.states["A"].call_count == 1  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_step_unknown_state_raises_fatal(self):
        sm = StateMachine(_three_state_workflow())
        with pytest.raises(FatalError, match="UNKNOWN"):
            await sm.step("UNKNOWN", None, _ctx())

    @pytest.mark.asyncio
    async def test_full_traversal_a_to_c(self):
        wf = _three_state_workflow()
        sm = StateMachine(wf)
        ctx = _ctx()
        current = wf.initial_state
        inp: object = "start"
        visited = []
        while not sm.is_terminal(current):
            t = await sm.step(current, inp, ctx)
            visited.append(current)
            current = t.next_state  # type: ignore[assignment]
            inp = t.output
        assert visited == ["A", "B"]
        assert sm.is_terminal("C")


class TestStateMachineIsTerminal:
    def test_none_is_terminal(self):
        sm = StateMachine(_three_state_workflow())
        assert sm.is_terminal(None) is True

    def test_terminal_state_id(self):
        sm = StateMachine(_three_state_workflow())
        assert sm.is_terminal("C") is True

    def test_non_terminal_state_id(self):
        sm = StateMachine(_three_state_workflow())
        assert sm.is_terminal("A") is False

    def test_isinstance_protocol(self):
        state = FakeState("X", next_state=None)
        assert isinstance(state, IState)
