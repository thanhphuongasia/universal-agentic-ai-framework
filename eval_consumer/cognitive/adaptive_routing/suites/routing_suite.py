"""Adaptive routing eval suite — chạy từ repo root:

    python -m evals.cognitive.adaptive_routing.suites.routing_suite

Kiểm tra difficulty_fn + tier_models có classify đúng không.
Truyền difficulty_fn vào RoutingTarget.build() — không có default.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from ryuu_eval_core.fixture_loader import FixtureLoader
from ryuu_eval_core.runner import EvalRunner

from ..targets.routing_target import ModelTierScorer, RoutingTarget

HERE = Path(__file__).parent
FIXTURES_DIR = HERE.parent / "fixtures"

_HARD_KW = ("analyze", "compare", "design", "evaluate", "phân tích", "so sánh", "thiết kế")
_TRIVIAL_KW = ("what is", "list", "define", "hi", "hello", "là gì", "liệt kê")


def _eval_difficulty_fn(query: str) -> str:
    """Deterministic classifier for eval suite — not for production use."""
    q = query.lower()
    if any(kw in q for kw in _HARD_KW) or len(q.split()) > 30:
        return "hard"
    if any(kw in q for kw in _TRIVIAL_KW) and len(q.split()) <= 10:
        return "trivial"
    return "medium"


async def main() -> None:
    cases = []
    for yml_file in sorted(FIXTURES_DIR.glob("*.yml")):
        cases.extend(FixtureLoader.load(yml_file))
    print(f"Loaded {len(cases)} fixture(s) from {FIXTURES_DIR}")

    target = RoutingTarget.build(difficulty_fn=_eval_difficulty_fn)
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
