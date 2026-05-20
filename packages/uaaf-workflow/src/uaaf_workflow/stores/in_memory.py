"""InMemoryCheckpointStore — dict-backed, no persistence. Default for tests. P7-T01."""

from __future__ import annotations

from uaaf_workflow.checkpoint import Checkpoint


class InMemoryCheckpointStore:
    """Dict-backed checkpoint store — no persistence. Default for test + dev."""

    def __init__(self) -> None:
        self._data: dict[str, list[Checkpoint]] = {}

    async def save(self, checkpoint: Checkpoint) -> None:
        bucket = self._data.setdefault(checkpoint.workflow_id, [])
        bucket.append(checkpoint)

    async def load_latest(self, workflow_id: str) -> Checkpoint | None:
        bucket = self._data.get(workflow_id)
        if not bucket:
            return None
        return max(bucket, key=lambda c: c.sequence)

    async def load_history(self, workflow_id: str) -> list[Checkpoint]:
        bucket = self._data.get(workflow_id, [])
        return sorted(bucket, key=lambda c: c.sequence)

    async def delete(self, workflow_id: str) -> None:
        self._data.pop(workflow_id, None)
