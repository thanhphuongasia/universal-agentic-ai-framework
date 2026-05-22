"""Tests for ryuu.refine_logger — RefineEvent + RefineLogger."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ryuu.refine_logger import RefineEvent, RefineLogger


class RefineEventTests(unittest.TestCase):
    def test_default_ts_is_iso8601(self) -> None:
        evt = RefineEvent(
            initial_prompt="p", feedback_history=["fb"],
            final_output="out", refine_count=1, passed=True,
        )
        assert evt.ts  # non-empty
        assert "T" in evt.ts  # ISO format

    def test_explicit_ts_preserved(self) -> None:
        evt = RefineEvent(
            initial_prompt="p", feedback_history=[], final_output="o",
            refine_count=0, passed=True, ts="2026-01-01T00:00:00+00:00",
        )
        assert evt.ts == "2026-01-01T00:00:00+00:00"

    def test_extra_metadata_optional(self) -> None:
        evt = RefineEvent(
            initial_prompt="p", feedback_history=[], final_output="o",
            refine_count=0, passed=True,
            extra={"project_id": "proj-1", "route": "POST /x"},
        )
        assert evt.extra["project_id"] == "proj-1"


class RefineLoggerTests(unittest.TestCase):
    def test_log_skips_zero_refine_count(self) -> None:
        """No training signal nếu LLM passed first try."""
        with TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            log = RefineLogger(path)
            log.log(RefineEvent(
                initial_prompt="p", feedback_history=[], final_output="o",
                refine_count=0, passed=True,
            ))
            assert not path.exists() or path.stat().st_size == 0

    def test_log_writes_jsonl_when_refined(self) -> None:
        with TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            log = RefineLogger(path)
            log.log(RefineEvent(
                initial_prompt="prompt1", feedback_history=["fb1"],
                final_output="output1", refine_count=1, passed=True,
            ))
            lines = path.read_text().strip().split("\n")
            assert len(lines) == 1
            data = json.loads(lines[0])
            assert data["initial_prompt"] == "prompt1"
            assert data["refine_count"] == 1
            assert data["passed"] is True

    def test_log_appends_multiple_events(self) -> None:
        with TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            log = RefineLogger(path)
            for i in range(3):
                log.log(RefineEvent(
                    initial_prompt=f"p{i}", feedback_history=[f"fb{i}"],
                    final_output=f"o{i}", refine_count=1, passed=True,
                ))
            assert len(path.read_text().strip().split("\n")) == 3

    def test_log_creates_parent_dirs(self) -> None:
        with TemporaryDirectory() as td:
            path = Path(td) / "deep" / "nested" / "log.jsonl"
            log = RefineLogger(path)
            log.log(RefineEvent(
                initial_prompt="p", feedback_history=["fb"], final_output="o",
                refine_count=1, passed=True,
            ))
            assert path.exists()

    def test_log_is_best_effort_swallows_errors(self) -> None:
        """Log to non-writable path → warning + return (no raise)."""
        # Use /dev/full-style path that may fail on write
        log = RefineLogger(Path("/proc/cannot_write_here.jsonl"))
        # Should not raise
        log.log(RefineEvent(
            initial_prompt="p", feedback_history=["fb"], final_output="o",
            refine_count=1, passed=True,
        ))

    def test_load_all_empty_when_missing(self) -> None:
        events = RefineLogger.load_all(Path("/tmp/definitely_nonexistent_xyz.jsonl"))
        assert events == []

    def test_load_all_skips_malformed_lines(self) -> None:
        with TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            path.write_text(
                '{"initial_prompt": "p", "feedback_history": [], "final_output": "o",'
                ' "refine_count": 1, "passed": true}\n'
                'not json at all\n'
                '{"initial_prompt": "p2", "feedback_history": [], "final_output": "o2",'
                ' "refine_count": 2, "passed": false}\n'
            )
            events = RefineLogger.load_all(path)
            assert len(events) == 2
            assert events[0].initial_prompt == "p"
            assert events[1].refine_count == 2

    def test_stats_empty(self) -> None:
        stats = RefineLogger.stats(Path("/tmp/empty_xyz.jsonl"))
        assert stats == {"total_events": 0}

    def test_stats_aggregates(self) -> None:
        with TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            log = RefineLogger(path)
            for rc, ok in [(1, True), (2, True), (3, False)]:
                log.log(RefineEvent(
                    initial_prompt="p", feedback_history=["fb"] * rc,
                    final_output="o", refine_count=rc, passed=ok,
                ))
            stats = RefineLogger.stats(path)
            assert stats["total_events"] == 3
            assert stats["avg_refines"] == 2.0
            assert stats["max_refines"] == 3
            assert stats["passed_rate"] == 2 / 3


if __name__ == "__main__":
    unittest.main()
