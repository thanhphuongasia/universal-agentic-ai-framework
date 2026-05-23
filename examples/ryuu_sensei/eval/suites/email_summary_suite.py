"""Email summary eval suite — chạy từ repo root:

    python -m examples.ryuu_sensei.eval.suites.email_summary_suite

Kiểm tra skill email_summary có tóm tắt ĐẦY ĐỦ tất cả story trong newsletter không.
Pass khi output đề cập đủ các keyword quan trọng, bỏ qua quảng cáo.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from ryuu_eval_core.fixture_loader import FixtureLoader
from ryuu_eval_core.models import EvalCase, ScoreResult
from ryuu_eval_core.runner import EvalRunner
from ryuu_eval_scorers.scorers import Composite, Constraint

from ..targets.email_summary_target import EmailSummaryTarget

HERE = Path(__file__).parent
SKILLS_DIR = HERE.parent.parent / "skills"
FIXTURES_DIR = HERE.parent.parent / "fixtures" / "email_summary"


def coverage_scorer():
    """Pass khi output nhắc đến tất cả story quan trọng, bỏ qua quảng cáo."""

    class _DynamicCoverage:
        scorer_id = "email-coverage"

        async def score(self, case: EvalCase, output: str) -> ScoreResult:
            must = case.expected.get("must_mention", []) if case.expected else []
            must_not = case.expected.get("must_not_mention", []) if case.expected else []

            checks = [
                Constraint(
                    scorer_id=f"mentions:{kw.lower()}",
                    constraint_fn=lambda out, _c, k=kw: k.lower() in out.lower(),
                )
                for kw in must
            ] + [
                Constraint(
                    scorer_id=f"excludes:{kw.lower()}",
                    constraint_fn=lambda out, _c, k=kw: k.lower() not in out.lower(),
                )
                for kw in must_not
            ]
            composite = Composite(scorer_id="email-coverage", scorers=checks, require_all=True)
            return await composite.score(case, output)

    return _DynamicCoverage()


async def main() -> None:
    loader = FixtureLoader()
    cases = []
    for yml_file in sorted(FIXTURES_DIR.glob("*.yml")):
        cases.extend(FixtureLoader.load(yml_file))
    print(f"Loaded {len(cases)} fixture(s) from {FIXTURES_DIR}")

    target = EmailSummaryTarget.build(skills_dir=SKILLS_DIR)
    runner = EvalRunner(suite_id="email_summary", target=target, scorers=[coverage_scorer()])
    result = await runner.run(cases)

    print(f"\n{'='*50}")
    print(f"Suite: email_summary  |  {result.passed_count}/{result.total_count} passed  ({result.pass_rate:.0%})")
    print(f"{'='*50}")

    for cr in result.cases:
        status = "PASS" if cr.passed else "FAIL"
        print(f"\n[{status}] {cr.case.case_id}")
        for s in cr.scores:
            icon = "✓" if s.passed else "✗"
            print(f"  {icon} {s.scorer_id}")
        if not cr.passed:
            if cr.error:
                print(f"  ERROR: {cr.error}")
            print(f"\n--- OUTPUT (800 chars) ---\n{cr.output[:800]}\n")


if __name__ == "__main__":
    asyncio.run(main())
