"""Per-case scoring: EvalRunner(scorer_for=...) + metadata_scorer_resolver.

Each case carries its own scoring spec in metadata["scoring"] (mirrors the
test_cases.scoring column). The resolver builds per-case scorers via
build_scorers; cases without a spec fall back to the suite-level scorers.
"""
from __future__ import annotations

import asyncio

from ryuu_eval_core import EvalRunner
from ryuu_eval_core.models import CaseResult, EvalCase
from ryuu_eval_scorers import ExactMatch, metadata_scorer_resolver


class _EchoTarget:
    """Returns the output stored in case.metadata['_out'] (test control)."""

    model = "stub"

    async def run(self, case: EvalCase) -> CaseResult:
        return CaseResult(case=case, output=case.metadata.get("_out", ""))


def _case(cid: str, out: str, scoring: dict | None) -> EvalCase:
    meta: dict = {"_out": out}
    if scoring is not None:
        meta["scoring"] = scoring
    # expected == out so a fallback ExactMatch passes; contains scorers ignore expected.
    return EvalCase(case_id=cid, input="x", expected=out, metadata=meta)


def _run(cases: list[EvalCase], *, suite_scorers, scorer_for) -> dict[str, CaseResult]:
    runner = EvalRunner(
        suite_id="s", target=_EchoTarget(),
        scorers=suite_scorers, scorer_for=scorer_for,
    )
    suite = asyncio.run(runner.run(cases))
    return {r.case.case_id: r for r in suite.cases}


def test_each_case_scored_by_its_own_spec():
    cases = [
        # forbidden 'GraphQL' must trip even though CREATE/READ are present
        _case("orders", "CREATE READ via GraphQL",
              {"scorers": [{"type": "contains", "config": {"required": ["CREATE", "READ"]}}],
               "combine": "and", "forbidden": ["GraphQL"]}),
        # needs all four ops; output has only two → fail
        _case("users", "CREATE READ",
              {"scorers": [{"type": "contains",
                            "config": {"required": ["CREATE", "READ", "UPDATE", "DELETE"]}}]}),
        # satisfies its own spec → pass
        _case("ok", "CREATE READ",
              {"scorers": [{"type": "contains", "config": {"required": ["CREATE", "READ"]}}]}),
    ]
    results = _run(cases, suite_scorers=[ExactMatch()],
                   scorer_for=metadata_scorer_resolver())

    assert not all(s.passed for s in results["orders"].scores)  # forbidden gate
    assert not all(s.passed for s in results["users"].scores)   # missing ops
    assert all(s.passed for s in results["ok"].scores)          # satisfied


def test_falls_back_to_suite_scorers_when_no_spec():
    # No metadata['scoring'] → resolver returns None → suite-level ExactMatch used.
    case = _case("plain", "hello", None)
    results = _run([case], suite_scorers=[ExactMatch()],
                   scorer_for=metadata_scorer_resolver())
    assert results["plain"].scores[0].scorer_id == "exact-match"
    assert results["plain"].scores[0].passed


def test_no_resolver_uses_suite_scorers():
    case = _case("plain", "hello", {"scorers": [{"type": "contains", "config": {"required": ["x"]}}]})
    # scorer_for=None → metadata spec ignored, suite ExactMatch applies
    results = _run([case], suite_scorers=[ExactMatch()], scorer_for=None)
    assert results["plain"].scores[0].scorer_id == "exact-match"
