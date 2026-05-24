"""Adaptive routing eval suite — chạy từ repo root:

    python -m evals.cognitive.adaptive_routing.suites.routing_suite

Kiểm tra _heuristic_difficulty() + tier_models có classify đúng không.
Zero cost — không gọi LLM.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from ryuu_eval_core.fixture_loader import FixtureLoader
from ryuu_eval_core.runner import EvalRunner

from ..targets.routing_target import ModelTierScorer, RoutingTarget

HERE = Path(__file__).parent
FIXTURES_DIR = HERE.parent / "fixtures"


async def main() -> None:
    cases = []
    for yml_file in sorted(FIXTURES_DIR.glob("*.yml")):
        cases.extend(FixtureLoader.load(yml_file))
    print(f"Loaded {len(cases)} fixture(s) from {FIXTURES_DIR}")

    target = RoutingTarget.build()
    runner = EvalRunner(suite_id="adaptive_routing", target=target, scorers=[ModelTierScorer()])
    result = await runner.run(cases)

    print(f"\n{'='*50}")
    print(f"Suite: adaptive_routing  |  {result.passed_count}/{result.total_count} passed  ({result.pass_rate:.0%})")
    print(f"{'='*50}")

    for cr in result.cases:
        status = "PASS" if cr.passed else "FAIL"
        print(f"\n[{status}] {cr.case.case_id}")
        for s in cr.scores:
            icon = "✓" if s.passed else "✗"
            print(f"  {icon} {s.scorer_id}: {s.reason}")


if __name__ == "__main__":
    asyncio.run(main())
