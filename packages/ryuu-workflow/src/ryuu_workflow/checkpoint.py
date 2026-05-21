"""ICheckpointStore Protocol + Checkpoint dataclass — P7-T01."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class Checkpoint:
    """Immutable snapshot of a workflow state's output."""

    workflow_id: str
    state_id: str
    output: Any
    timestamp: float
    sequence: int
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ICheckpointStore(Protocol):
    """Persist and retrieve workflow checkpoints."""

    async def save(self, checkpoint: Checkpoint) -> None: ...

    async def load_latest(self, workflow_id: str) -> Checkpoint | None: ...

    async def load_history(self, workflow_id: str) -> list[Checkpoint]: ...

    async def delete(self, workflow_id: str) -> None: ...


def make_checkpoint(
    workflow_id: str,
    state_id: str,
    output: Any,
    sequence: int,
    metadata: dict[str, Any] | None = None,
) -> Checkpoint:
    return Checkpoint(
        workflow_id=workflow_id,
        state_id=state_id,
        output=output,
        timestamp=time.time(),
        sequence=sequence,
        metadata=metadata or {},
    )
