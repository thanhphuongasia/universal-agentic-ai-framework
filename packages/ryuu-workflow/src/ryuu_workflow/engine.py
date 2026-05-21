"""IWorkflowEngine Protocol + WorkflowEngine — P7-T03/T04."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

import anyio

from ryuu_workflow.errors import DegradedError, FatalError, RetryableError, retry_policy
from ryuu_workflow.context import ExecutionContext
from ryuu_workflow.checkpoint import Checkpoint, ICheckpointStore
from ryuu_workflow.state_machine import StateMachine, Workflow

logger = logging.getLogger(__name__)


class WorkflowStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


@dataclass
class WorkflowResult:
    workflow_id: str
    status: WorkflowStatus
    final_state: str | None
    output: Any
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    checkpoints_saved: int = 0


@runtime_checkable
class IWorkflowEngine(Protocol):
    async def run(
        self,
        workflow: Workflow,
        initial_input: Any,
        context: ExecutionContext,
    ) -> WorkflowResult: ...

    async def resume(
        self,
        workflow_id: str,
        workflow: Workflow,
        context: ExecutionContext,
    ) -> WorkflowResult: ...


@dataclass
class WorkflowEngine:
    checkpoint_store: ICheckpointStore
    max_state_retries: int = 3
    max_transitions: int = 1000

    async def run(
        self,
        workflow: Workflow,
        initial_input: Any,
        context: ExecutionContext,
    ) -> WorkflowResult:
        machine = StateMachine(workflow)
        try:
            machine.validate()
        except FatalError as exc:
            return WorkflowResult(
                workflow_id=workflow.workflow_id,
                status=WorkflowStatus.FAILED,
                final_state=None,
                output=None,
                error=str(exc),
            )
        return await self._run_loop(
            workflow=workflow,
            machine=machine,
            current_state=workflow.initial_state,
            current_input=initial_input,
            sequence=0,
            context=context,
        )

    async def resume(
        self,
        workflow_id: str,
        workflow: Workflow,
        context: ExecutionContext,
    ) -> WorkflowResult:
        checkpoint = await self.checkpoint_store.load_latest(workflow_id)
        if checkpoint is None:
            return await self.run(workflow, initial_input=None, context=context)

        next_state = checkpoint.metadata.get("next_state")
        if next_state is None:
            # Last checkpoint was terminal
            return WorkflowResult(
                workflow_id=workflow_id,
                status=WorkflowStatus.COMPLETED,
                final_state=checkpoint.state_id,
                output=checkpoint.output,
                checkpoints_saved=checkpoint.sequence + 1,
            )

        machine = StateMachine(workflow)
        try:
            machine.validate()
        except FatalError as exc:
            return WorkflowResult(
                workflow_id=workflow_id,
                status=WorkflowStatus.FAILED,
                final_state=None,
                output=None,
                error=str(exc),
            )

        if next_state not in workflow.states:
            return WorkflowResult(
                workflow_id=workflow_id,
                status=WorkflowStatus.FAILED,
                final_state=checkpoint.state_id,
                output=checkpoint.output,
                error=f"Checkpoint next_state {next_state!r} not found in workflow states",
            )

        return await self._run_loop(
            workflow=workflow,
            machine=machine,
            current_state=next_state,
            current_input=checkpoint.output,
            sequence=checkpoint.sequence + 1,
            context=context,
        )

    async def _run_loop(
        self,
        workflow: Workflow,
        machine: StateMachine,
        current_state: str,
        current_input: Any,
        sequence: int,
        context: ExecutionContext,
    ) -> WorkflowResult:
        transitions = 0
        last_executed_state: str | None = None

        while not machine.is_terminal(current_state):
            if transitions >= self.max_transitions:
                return WorkflowResult(
                    workflow_id=workflow.workflow_id,
                    status=WorkflowStatus.FAILED,
                    final_state=current_state,
                    output=current_input,
                    error="max transitions exceeded — possible infinite loop",
                    checkpoints_saved=sequence,
                )

            transition = None
            attempt = 0
            while attempt < self.max_state_retries:
                try:
                    transition = await machine.step(current_state, current_input, context)
                    break
                except RetryableError as exc:
                    decision = retry_policy(exc, attempt)
                    logger.warning(
                        "Retryable error in state %r (attempt %d): %s",
                        current_state, attempt, exc,
                    )
                    if decision.wait_seconds:
                        await anyio.sleep(decision.wait_seconds)
                    attempt += 1
                except DegradedError as exc:
                    logger.warning("Degraded error in state %r: %s", current_state, exc)
                    break
                except FatalError as exc:
                    return WorkflowResult(
                        workflow_id=workflow.workflow_id,
                        status=WorkflowStatus.FAILED,
                        final_state=current_state,
                        output=current_input,
                        error=str(exc),
                        checkpoints_saved=sequence,
                    )

            if attempt >= self.max_state_retries and transition is None:
                return WorkflowResult(
                    workflow_id=workflow.workflow_id,
                    status=WorkflowStatus.FAILED,
                    final_state=current_state,
                    output=current_input,
                    error=f"max retries exceeded for state {current_state!r}",
                    checkpoints_saved=sequence,
                )

            if transition is None:
                # DegradedError with no transition — treat state as failed
                return WorkflowResult(
                    workflow_id=workflow.workflow_id,
                    status=WorkflowStatus.FAILED,
                    final_state=current_state,
                    output=current_input,
                    error=f"State {current_state!r} raised DegradedError without returning transition",
                    checkpoints_saved=sequence,
                )

            cp = Checkpoint(
                workflow_id=workflow.workflow_id,
                state_id=current_state,
                output=transition.output,
                timestamp=time.time(),
                sequence=sequence,
                metadata={"next_state": transition.next_state},
            )
            await self.checkpoint_store.save(cp)
            sequence += 1
            transitions += 1
            last_executed_state = current_state

            current_state = transition.next_state  # type: ignore[assignment]
            current_input = transition.output

        return WorkflowResult(
            workflow_id=workflow.workflow_id,
            status=WorkflowStatus.COMPLETED,
            final_state=current_state or last_executed_state,
            output=current_input,
            checkpoints_saved=sequence,
        )
