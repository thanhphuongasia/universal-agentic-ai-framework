"""Smoke tests for ryuu-eval package."""
from __future__ import annotations

import pytest


# --- models ---

def test_eval_case_construction() -> None:
    from ryuu_eval.models import EvalCase
    c = EvalCase(case_id="c1", input="what is 2+2?", expected="4")
    assert c.case_id == "c1"
    assert c.expected == "4"
    assert c.metadata == {}


def test_suite_result_pass_rate_empty() -> None:
    from ryuu_eval.models import SuiteResult
    s = SuiteResult(suite_id="s1")
    assert s.pass_rate == 0.0
    assert s.total_count == 0


def test_case_result_passed_no_error_all_scores() -> None:
    from ryuu_eval.models import CaseResult, EvalCase, ScoreResult
    case = EvalCase(case_id="c1", input="x")
    cr = CaseResult(
        case=case,
        output="y",
        scores=[ScoreResult(scorer_id="em", score=1.0, passed=True)],
    )
    assert cr.passed


def test_case_result_failed_on_error() -> None:
    from ryuu_eval.models import CaseResult, EvalCase
    cr = CaseResult(case=EvalCase(case_id="c1", input="x"), output="", error="timeout")
    assert not cr.passed


def test_suite_result_pass_rate() -> None:
    from ryuu_eval.models import CaseResult, EvalCase, ScoreResult, SuiteResult
    s = SuiteResult(suite_id="s1")
    s.cases.append(CaseResult(
        case=EvalCase(case_id="c1", input="x"),
        output="y",
        scores=[ScoreResult(scorer_id="em", score=1.0, passed=True)],
    ))
    s.cases.append(CaseResult(
        case=EvalCase(case_id="c2", input="x"),
        output="",
        error="fail",
    ))
    assert s.passed_count == 1
    assert s.total_count == 2
    assert s.pass_rate == 0.5


# --- scorers ---

async def test_exact_match_passes() -> None:
    from ryuu_eval.models import EvalCase
    from ryuu_eval.scorers import ExactMatch
    s = ExactMatch()
    case = EvalCase(case_id="c1", input="q", expected="Paris")
    result = await s.score(case, "Paris")
    assert result.passed
    assert result.score == 1.0


async def test_exact_match_fails() -> None:
    from ryuu_eval.models import EvalCase
    from ryuu_eval.scorers import ExactMatch
    s = ExactMatch()
    case = EvalCase(case_id="c1", input="q", expected="Paris")
    result = await s.score(case, "London")
    assert not result.passed
    assert result.score == 0.0


async def test_constraint_scorer() -> None:
    from ryuu_eval.models import EvalCase
    from ryuu_eval.scorers import Constraint
    s = Constraint("length-ok", lambda output, case: len(output) > 5)
    case = EvalCase(case_id="c1", input="q")
    assert (await s.score(case, "long enough")).passed
    assert not (await s.score(case, "no")).passed


async def test_threshold_scorer() -> None:
    from ryuu_eval.models import EvalCase
    from ryuu_eval.scorers import Threshold
    s = Threshold("overlap", 0.5, lambda output, case: 0.8)
    case = EvalCase(case_id="c1", input="q")
    result = await s.score(case, "anything")
    assert result.passed
    assert result.score == 0.8


async def test_composite_require_all() -> None:
    from ryuu_eval.models import EvalCase
    from ryuu_eval.scorers import Composite, ExactMatch, Constraint
    s = Composite("combo", [
        ExactMatch(),
        Constraint("len", lambda o, c: len(o) > 0),
    ], require_all=True)
    case = EvalCase(case_id="c1", input="q", expected="Paris")
    assert (await s.score(case, "Paris")).passed
    assert not (await s.score(case, "London")).passed


# --- fixture_loader ---

def test_fixture_loader_from_list() -> None:
    from ryuu_eval.fixture_loader import FixtureLoader
    data = [
        {"case_id": "c1", "input": "hello", "expected": "world"},
        {"input": "foo"},
    ]
    cases = FixtureLoader.load_json(data)
    assert len(cases) == 2
    assert cases[0].case_id == "c1"
    assert cases[1].case_id == "1"
    assert cases[1].expected is None


# --- runner ---

async def test_eval_runner_basic() -> None:
    from ryuu_eval.models import CaseResult, EvalCase
    from ryuu_eval.runner import EvalRunner
    from ryuu_eval.scorers import ExactMatch

    class FakeTarget:
        async def run(self, case: EvalCase) -> CaseResult:
            return CaseResult(case=case, output=str(case.expected))

    cases = [
        EvalCase(case_id="c1", input="q1", expected="Paris"),
        EvalCase(case_id="c2", input="q2", expected="Berlin"),
    ]
    runner = EvalRunner("test-suite", FakeTarget(), [ExactMatch()])
    result = await runner.run(cases)
    assert result.suite_id == "test-suite"
    assert result.total_count == 2
    assert result.passed_count == 2
    assert result.pass_rate == 1.0


async def test_eval_runner_handles_target_error() -> None:
    from ryuu_eval.models import CaseResult, EvalCase
    from ryuu_eval.runner import EvalRunner
    from ryuu_eval.scorers import ExactMatch

    class BrokenTarget:
        async def run(self, case: EvalCase) -> CaseResult:
            raise RuntimeError("timeout")

    cases = [EvalCase(case_id="c1", input="q")]
    runner = EvalRunner("s", BrokenTarget(), [ExactMatch()])
    result = await runner.run(cases)
    assert result.cases[0].error == "timeout"
    assert not result.cases[0].passed


# --- renderers ---

async def test_terminal_renderer() -> None:
    from ryuu_eval.models import CaseResult, EvalCase, ScoreResult, SuiteResult
    from ryuu_eval.renderers.terminal import TerminalRenderer

    suite = SuiteResult(suite_id="my-suite")
    suite.cases.append(CaseResult(
        case=EvalCase(case_id="c1", input="q"),
        output="ok",
        scores=[ScoreResult(scorer_id="em", score=1.0, passed=True)],
    ))
    text = TerminalRenderer().render(suite)
    assert "my-suite" in text
    assert "c1" in text


def test_api_renderer() -> None:
    from ryuu_eval.models import CaseResult, EvalCase, SuiteResult
    from ryuu_eval.renderers.api import ApiRenderer

    suite = SuiteResult(suite_id="s1")
    suite.cases.append(CaseResult(case=EvalCase(case_id="c1", input="q"), output="ans"))
    data = ApiRenderer().render(suite)
    assert data["suite_id"] == "s1"
    assert len(data["cases"]) == 1
    assert data["cases"][0]["case_id"] == "c1"


def test_github_actions_renderer_all_pass() -> None:
    from ryuu_eval.models import CaseResult, EvalCase, ScoreResult, SuiteResult
    from ryuu_eval.renderers.github_actions import GitHubActionsRenderer

    suite = SuiteResult(suite_id="ci-suite")
    suite.cases.append(CaseResult(
        case=EvalCase(case_id="c1", input="q"),
        output="ok",
        scores=[ScoreResult(scorer_id="em", score=1.0, passed=True)],
    ))
    text = GitHubActionsRenderer().render(suite)
    assert "::notice::" in text
    assert "all 1 cases passed" in text
