"""IState Protocol + StateTransition + Workflow dataclass + StateMachine — P7-T02."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from uaaf.observability.errors import FatalError
from uaaf.runtime.context import ExecutionContext


@dataclass
class StateTransition:
    """Result of a state execution — carries next state + output."""

    next_state: str | None  # None = terminal
    output: Any
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class IState(Protocol):
    """A single node in a workflow state graph."""

    state_id: str

    async def execute(
        self, input: Any, context: ExecutionContext
    ) -> StateTransition: ...


@dataclass(frozen=True)
class Workflow:
    """Immutable definition of a state graph."""

    workflow_id: str
    states: dict[str, IState]
    initial_state: str
    terminal_states: frozenset[str]


class StateMachine:
    """Drives state transitions for a Workflow definition."""

    def __init__(self, workflow: Workflow) -> None:
        self._workflow = workflow

    def validate(self) -> None:
        """Raise FatalError if the workflow graph is structurally invalid."""
        wf = self._workflow
        if wf.initial_state not in wf.states:
            raise FatalError(
                f"initial_state {wf.initial_state!r} not found in workflow.states"
            )
        for state_id, state in wf.states.items():
            if state.state_id != state_id:
                raise FatalError(
                    f"State key {state_id!r} does not match state.state_id {state.state_id!r}"
                )

    async def step(
        self,
        current_state_id: str,
        input: Any,
        context: ExecutionContext,
    ) -> StateTransition:
        """Execute the state identified by *current_state_id*."""
        state = self._workflow.states.get(current_state_id)
        if state is None:
            raise FatalError(
                f"State {current_state_id!r} not found in workflow {self._workflow.workflow_id!r}"
            )
        return await state.execute(input, context)

    def is_terminal(self, state_id: str | None) -> bool:
        if state_id is None:
            return True
        return state_id in self._workflow.terminal_states
