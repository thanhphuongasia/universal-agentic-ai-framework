"""FileCheckpointStore — JSON-on-disk persistence with atomic writes. P7-T05."""

from __future__ import annotations

import json
import os
from pathlib import Path

from uaaf.observability.errors import FatalError
from uaaf.workflow.checkpoint import Checkpoint


class FileCheckpointStore:
    """JSON-file-backed checkpoint store. Output must be JSON-serializable.

    Layout: <base_dir>/<workflow_id>/<sequence>.json
    Atomic write: write to .tmp then os.replace(.tmp, .json).
    Single-writer per workflow_id — concurrent writes to the same workflow are not safe.
    """

    def __init__(self, base_dir: Path) -> None:
        self._base = base_dir

    def _wf_dir(self, workflow_id: str) -> Path:
        return self._base / workflow_id

    def _cp_path(self, workflow_id: str, sequence: int) -> Path:
        return self._wf_dir(workflow_id) / f"{sequence}.json"

    async def save(self, checkpoint: Checkpoint) -> None:
        wf_dir = self._wf_dir(checkpoint.workflow_id)
        wf_dir.mkdir(parents=True, exist_ok=True)
        try:
            data = json.dumps(
                {
                    "workflow_id": checkpoint.workflow_id,
                    "state_id": checkpoint.state_id,
                    "output": checkpoint.output,
                    "timestamp": checkpoint.timestamp,
                    "sequence": checkpoint.sequence,
                    "metadata": checkpoint.metadata,
                }
            )
        except (TypeError, ValueError) as exc:
            raise FatalError(
                f"Checkpoint output for workflow {checkpoint.workflow_id!r} state "
                f"{checkpoint.state_id!r} is not JSON-serializable: {exc}"
            ) from exc

        target = self._cp_path(checkpoint.workflow_id, checkpoint.sequence)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(data, encoding="utf-8")
        os.replace(tmp, target)

    async def load_latest(self, workflow_id: str) -> Checkpoint | None:
        wf_dir = self._wf_dir(workflow_id)
        if not wf_dir.exists():
            return None
        checkpoints = await self.load_history(workflow_id)
        return checkpoints[-1] if checkpoints else None

    async def load_history(self, workflow_id: str) -> list[Checkpoint]:
        wf_dir = self._wf_dir(workflow_id)
        if not wf_dir.exists():
            return []
        checkpoints: list[Checkpoint] = []
        for cp_file in sorted(wf_dir.glob("*.json"), key=lambda p: int(p.stem)):
            raw = json.loads(cp_file.read_text(encoding="utf-8"))
            checkpoints.append(
                Checkpoint(
                    workflow_id=raw["workflow_id"],
                    state_id=raw["state_id"],
                    output=raw["output"],
                    timestamp=raw["timestamp"],
                    sequence=raw["sequence"],
                    metadata=raw.get("metadata", {}),
                )
            )
        return checkpoints

    async def delete(self, workflow_id: str) -> None:
        wf_dir = self._wf_dir(workflow_id)
        if not wf_dir.exists():
            return
        for f in wf_dir.iterdir():
            f.unlink(missing_ok=True)
        try:
            wf_dir.rmdir()
        except OSError:
            pass  # non-empty dir (e.g., raced with another writer) — ignore
