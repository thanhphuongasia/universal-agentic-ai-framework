"""Tests for Step 1-3 + 7 — eval framework v2 (templates, streaming, YAML)."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ryuu_eval_core import (
    CaseResult,
    EvalCase,
    EvalCaseTemplate,
    EvalRunner,
    FixtureLoader,
    ProgressEvent,
    ScoreResult,
)


class EvalCaseTemplateTests(unittest.TestCase):
    def test_minimal_construction(self) -> None:
        tpl = EvalCaseTemplate(template_id="t1", suite_id="s1", title="T1")
        assert tpl.template_id == "t1"
        assert tpl.examples == []
        assert tpl.tags == []

    def test_full_construction_with_schemas(self) -> None:
        tpl = EvalCaseTemplate(
            template_id="crud_happy_path",
            suite_id="crud_matrix",
            title="CRUD Happy Path",
            description="Standard happy case",
            input_schema={"type": "object", "properties": {"route": {"type": "string"}}},
            expected_schema={"type": "object", "properties": {"cells": {"type": "array"}}},
            examples=[{"input": {"route": "POST /x"}, "expected": {"cells": []}}],
            tags=["smoke", "happy"],
        )
        assert "smoke" in tpl.tags
        assert tpl.examples[0]["input"]["route"] == "POST /x"


class ProgressEventTests(unittest.TestCase):
    def test_auto_ts_set(self) -> None:
        ev = ProgressEvent(type="suite_start", payload={"x": 1})
        assert ev.ts > 0
        assert ev.payload == {"x": 1}

    def test_explicit_ts_preserved(self) -> None:
        ev = ProgressEvent(type="case_start", ts=1234567.0)
        assert ev.ts == 1234567.0

    def test_case_id_optional(self) -> None:
        ev = ProgressEvent(type="suite_start")
        assert ev.case_id is None


class StreamingRunnerTests(unittest.IsolatedAsyncioTestCase):
    """Test Step 2 — EvalRunner.stream() yields proper events."""

    async def test_stream_emits_lifecycle_events(self) -> None:
        class FakeTarget:
            async def run(self, case):
                return CaseResult(case=case, output="OK", scores=[
                    ScoreResult("dummy", 1.0, True),
                ])

        class PassScorer:
            scorer_id = "passing"
            async def score(self, case, output):
                return ScoreResult(self.scorer_id, 1.0, True)

        cases = [EvalCase(case_id="c1", input="x"), EvalCase(case_id="c2", input="y")]
        runner = EvalRunner(suite_id="test", target=FakeTarget(), scorers=[PassScorer()])

        events = []
        async for ev in runner.stream(cases):
            events.append(ev)

        types = [e.type for e in events]
        # Expected sequence: suite_start, case_start, case_done, case_start, case_done, suite_done
        assert types[0] == "suite_start"
        assert types[-1] == "suite_done"
        assert types.count("case_start") == 2
        assert types.count("case_done") == 2

    async def test_stream_surfaces_refine_count(self) -> None:
        class FakeTargetWithRefines:
            _meta = {"refine_count": 2, "feedback_history": ["fb1", "fb2"]}

            async def run(self, case):
                return CaseResult(case=case, output="ok", scores=[
                    ScoreResult("s", 1.0, True),
                ])

            def last_refine_meta(self):
                return self._meta

        class PassScorer:
            scorer_id = "p"
            async def score(self, case, output):
                return ScoreResult(self.scorer_id, 1.0, True)

        cases = [EvalCase(case_id="c1", input="x")]
        runner = EvalRunner(suite_id="t", target=FakeTargetWithRefines(), scorers=[PassScorer()])

        events = []
        async for ev in runner.stream(cases):
            events.append(ev)

        refine_events = [e for e in events if e.type == "refine_done"]
        assert len(refine_events) == 1
        assert refine_events[0].payload["refine_count"] == 2
        assert refine_events[0].payload["feedback_history"] == ["fb1", "fb2"]

    async def test_stream_emits_error_event(self) -> None:
        class BrokenTarget:
            async def run(self, case):
                raise RuntimeError("simulated failure")

        cases = [EvalCase(case_id="c1", input="x")]
        runner = EvalRunner(suite_id="t", target=BrokenTarget(), scorers=[])

        events = []
        async for ev in runner.stream(cases):
            events.append(ev)

        error_events = [e for e in events if e.type == "error"]
        assert len(error_events) == 1
        assert "simulated failure" in error_events[0].payload["message"]


class YamlFixtureLoaderTests(unittest.TestCase):
    """Test Step 7 — YAML + !py escape hatch."""

    def test_loads_yaml_cases(self) -> None:
        with TemporaryDirectory() as td:
            p = Path(td) / "cases.yml"
            p.write_text("""
cases:
  - case_id: c1
    input: "What is 2+2?"
    expected: "4"
  - case_id: c2
    input: "What is 10*5?"
    expected: "50"
""")
            cases = FixtureLoader.load(p)
            assert len(cases) == 2
            assert cases[0].case_id == "c1"
            assert cases[1].expected == "50"

    def test_yaml_py_escape_evaluates_expression(self) -> None:
        with TemporaryDirectory() as td:
            p = Path(td) / "cases.yml"
            p.write_text("""
cases:
  - case_id: dynamic
    input: "current value"
    expected: !py "1 + 2 + 3"
""")
            cases = FixtureLoader.load(p)
            assert cases[0].expected == 6

    def test_loads_template_yaml(self) -> None:
        with TemporaryDirectory() as td:
            p = Path(td) / "happy.template.yml"
            p.write_text("""
template_id: crud_happy
suite_id: crud_matrix
title: Happy Path
description: Simple CRUD case
input_schema:
  type: object
  properties:
    route:
      type: string
expected_schema:
  type: object
examples:
  - input: {route: "POST /x"}
    expected: {cells: []}
tags: [smoke]
""")
            tpl = FixtureLoader.load_template(p)
            assert tpl.template_id == "crud_happy"
            assert tpl.suite_id == "crud_matrix"
            assert tpl.tags == ["smoke"]

    def test_list_templates_discovers_multiple(self) -> None:
        """Q1 — multiple templates per suite, all discovered."""
        with TemporaryDirectory() as td:
            suite_dir = Path(td) / "suite"
            templates_dir = suite_dir / "templates"
            templates_dir.mkdir(parents=True)

            for tid in ["happy", "edge", "regression"]:
                (templates_dir / f"{tid}.yml").write_text(f"""
template_id: {tid}
suite_id: crud_matrix
title: {tid.title()}
""")
            templates = FixtureLoader.list_templates(suite_dir)
            ids = {t.template_id for t in templates}
            assert ids == {"happy", "edge", "regression"}

    def test_list_templates_handles_missing_dir(self) -> None:
        templates = FixtureLoader.list_templates("/tmp/definitely_missing_xyz")
        assert templates == []

    def test_json_backward_compat(self) -> None:
        """Legacy JSON loading still works."""
        with TemporaryDirectory() as td:
            p = Path(td) / "cases.json"
            p.write_text('[{"case_id": "c1", "input": "x", "expected": "y"}]')
            cases = FixtureLoader.load(p)
            assert cases[0].input == "x"


if __name__ == "__main__":
    unittest.main()
