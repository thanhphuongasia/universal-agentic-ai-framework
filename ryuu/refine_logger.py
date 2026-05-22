"""RefineLogger — capture Evaluator refine cycles for prompt-optimization training.

When ``ryuu.Evaluator.run()`` retries due to verifier failure, it can attach a
``RefineLogger`` to capture each refine event as JSONL. These events become the
training signal for ``ryuu.PromptOptimizer`` — let the optimizer learn từ real
production failures và iteratively improve prompts.

Use case::

    from ryuu import Agent
    from ryuu.facades.evaluator import Evaluator
    from ryuu.refine_logger import RefineLogger

    logger = RefineLogger(log_path=Path("artifacts/refine_history.jsonl"))
    evaluator = Evaluator(
        generator=Agent(model="gpt-4o-mini", instructions="..."),
        verifier=my_verifier,
        max_refines=2,
        refine_logger=logger,    # optional — only logs when refine_count > 0
    )

    result = await evaluator.run("classify these items")

    # Later, run prompt optimization từ accumulated events:
    events = RefineLogger.load_all(Path("artifacts/refine_history.jsonl"))
    # Feed to PromptOptimizer as EvalCases — see ryuu.prompt_optimizer docs

The logger is intentionally minimal — it captures one event per refine cycle,
nothing more. Project-specific metadata (entity annotations, route labels) can
be attached via the ``extra=`` dict on each ``RefineEvent``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RefineEvent:
    """One Evaluator refine cycle event.

    Captured when Evaluator.run() encounters verifier failure và retries.
    Contains everything needed to reproduce the LLM exchange và score
    candidate prompts against the corrected (final) output.
    """

    initial_prompt: str
    """The first prompt sent to the LLM (before any feedback appended)."""

    feedback_history: list[str]
    """Per-iteration feedback từ verifier, in order. Length == refine_count."""

    final_output: str
    """The final LLM output (corrected if passed, best-effort if max_refines exhausted)."""

    refine_count: int
    """How many retry iterations occurred (0 = passed first try, n = had n refines)."""

    passed: bool
    """Whether the verifier finally accepted the output."""

    ts: str = ""
    """ISO 8601 timestamp of when this event completed."""

    extra: dict[str, Any] = field(default_factory=dict)
    """Project-specific metadata (entity context, route label, project_id, etc.)."""

    def __post_init__(self) -> None:
        if not self.ts:
            self.ts = datetime.now(timezone.utc).isoformat()


class RefineLogger:
    """Append-only JSONL logger for refine events. Thread-safe via append-mode IO.

    Best-effort logging — any IO failure is logged at warning level và swallowed.
    Never raises from log() so the calling Evaluator flow stays robust.
    """

    def __init__(self, log_path: Path) -> None:
        self._log_path = log_path

    @property
    def log_path(self) -> Path:
        return self._log_path

    def log(self, event: RefineEvent) -> None:
        """Append one event to JSONL. Skip if refine_count == 0 (no training signal)."""
        if event.refine_count == 0:
            return
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")
        except Exception as exc:  # noqa: BLE001 — best-effort
            logger.warning("RefineLogger.log failed (skipped): %s", exc)

    @staticmethod
    def load_all(log_path: Path) -> list[RefineEvent]:
        """Read all events từ JSONL. Returns [] if file missing or empty."""
        if not log_path.exists():
            return []
        events: list[RefineEvent] = []
        for line in log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                events.append(RefineEvent(**data))
            except (json.JSONDecodeError, TypeError) as exc:
                logger.warning("Skipping malformed line: %s", exc)
        return events

    @staticmethod
    def stats(log_path: Path) -> dict[str, Any]:
        """Quick aggregate stats over the log. Useful for monitoring."""
        events = RefineLogger.load_all(log_path)
        if not events:
            return {"total_events": 0}
        counts = [e.refine_count for e in events]
        return {
            "total_events": len(events),
            "avg_refines": sum(counts) / len(counts),
            "max_refines": max(counts),
            "passed_rate": sum(1 for e in events if e.passed) / len(events),
        }


__all__ = ["RefineEvent", "RefineLogger"]
