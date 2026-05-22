"""Tests for Evaluator + RefineLogger integration."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

from ryuu.facades.evaluator import Evaluator
from ryuu.refine_logger import RefineLogger


class EvaluatorRefineLoggingTests(unittest.IsolatedAsyncioTestCase):
    def _make_evaluator(self, generator_outputs: list[str], verifier_results: list[tuple[bool, str]],
                        logger=None, max_refines=2, extra_metadata=None):
        """Build evaluator with mocked agent returning fixed outputs."""
        agent = MagicMock()
        call_count = {"i": 0}

        async def fake_run(prompt):
            i = call_count["i"]
            call_count["i"] += 1
            result = MagicMock()
            result.output = generator_outputs[min(i, len(generator_outputs) - 1)]
            return result

        agent.run = fake_run

        verifier_count = {"i": 0}

        def fake_verifier(output):
            i = verifier_count["i"]
            verifier_count["i"] += 1
            return verifier_results[min(i, len(verifier_results) - 1)]

        return Evaluator(
            generator=agent,
            verifier=fake_verifier,
            max_refines=max_refines,
            refine_logger=logger,
            extra_metadata=extra_metadata or {},
        )

    async def test_no_log_when_passed_first_try(self) -> None:
        """refine_count = 0 → no event written."""
        with TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            logger = RefineLogger(path)
            ev = self._make_evaluator(
                generator_outputs=["good output"],
                verifier_results=[(True, "")],
                logger=logger,
            )
            result = await ev.run("input")
            assert result == "good output"
            assert not path.exists() or path.stat().st_size == 0

    async def test_logs_when_refined_once(self) -> None:
        """LLM fails once, refines, passes → log 1 event with refine_count=1."""
        with TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            logger = RefineLogger(path)
            ev = self._make_evaluator(
                generator_outputs=["bad output", "good output"],
                verifier_results=[(False, "wrong format"), (True, "")],
                logger=logger,
            )
            result = await ev.run("input")
            assert result == "good output"
            assert path.exists()
            entry = json.loads(path.read_text().strip())
            assert entry["initial_prompt"] == "input"
            assert entry["refine_count"] == 1
            assert entry["passed"] is True
            assert entry["feedback_history"] == ["wrong format"]
            assert entry["final_output"] == "good output"

    async def test_logs_when_max_refines_exhausted(self) -> None:
        """LLM keeps failing → log event with passed=False."""
        with TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            logger = RefineLogger(path)
            ev = self._make_evaluator(
                generator_outputs=["bad1", "bad2", "bad3"],
                verifier_results=[(False, "fb1"), (False, "fb2"), (False, "fb3")],
                logger=logger,
                max_refines=2,
            )
            result = await ev.run("input")
            assert result == "bad3"
            entry = json.loads(path.read_text().strip())
            assert entry["passed"] is False
            assert entry["refine_count"] == 3  # max_refines + 1 attempts total

    async def test_extra_metadata_attached(self) -> None:
        with TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            logger = RefineLogger(path)
            ev = self._make_evaluator(
                generator_outputs=["bad", "good"],
                verifier_results=[(False, "fb"), (True, "")],
                logger=logger,
                extra_metadata={"project_id": "demo", "route": "POST /x"},
            )
            await ev.run("input")
            entry = json.loads(path.read_text().strip())
            assert entry["extra"] == {"project_id": "demo", "route": "POST /x"}

    async def test_works_without_logger(self) -> None:
        """No logger attached → no-op, normal Evaluator behavior."""
        ev = self._make_evaluator(
            generator_outputs=["bad", "good"],
            verifier_results=[(False, "fb"), (True, "")],
            logger=None,
        )
        result = await ev.run("input")
        assert result == "good"


if __name__ == "__main__":
    unittest.main()
