"""Model routing E2E eval suite — chạy từ repo root:

    python -m examples.ryuu_sensei.eval.suites.model_routing_e2e_suite

⚠️  Tốn LLM call thật (OpenAI API). Dùng OPENAI_API_KEY.
    ~4 cases × ~$0.0002 = < $0.001 mỗi lần chạy.

Kiểm tra:
  1. model-tier  — routing có chọn đúng model không (heuristic)
  2. keyword     — LLM output có đủ nội dung kỳ vọng không
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from ryuu_eval_core.fixture_loader import FixtureLoader
from ryuu_eval_core.runner import EvalRunner

from ..targets.routing_e2e_target import KeywordScorer, ModelTierScorer, RoutingE2ETarget

HERE = Path(__file__).parent
FIXTURES_DIR = HERE.parent.parent / "fixtures" / "model_routing"


async def main() -> None:
    cases = []
    for yml_file in sorted(FIXTURES_DIR.glob("routing_e2e_*.yml")):
        cases.extend(FixtureLoader.load(yml_file))
    print(f"Loaded {len(cases)} fixture(s) from {FIXTURES_DIR}")
    print("⚠️  Calling real LLM — this costs ~$0.001\n")

    target = RoutingE2ETarget.build(adaptive_routing=True)
    runner = EvalRunner(
        suite_id="model_routing_e2e",
        target=target,
        scorers=[ModelTierScorer(), KeywordScorer()],
    )
    result = await runner.run(cases)

    print(f"\n{'='*55}")
    print(f"Suite: model_routing_e2e  |  {result.passed_count}/{result.total_count} passed  ({result.pass_rate:.0%})")
    print(f"{'='*55}")

    for cr in result.cases:
        status = "PASS" if cr.passed else "FAIL"
        print(f"\n[{status}] {cr.case.case_id}")
        for s in cr.scores:
            icon = "✓" if s.passed else "✗"
            print(f"  {icon} {s.scorer_id}: {s.reason}")
        if not cr.passed:
            if cr.error:
                print(f"  ERROR: {cr.error}")
            else:
                try:
                    text = json.loads(cr.output).get("text", cr.output)
                    print(f"\n--- OUTPUT (400 chars) ---\n{text[:400]}\n")
                except (json.JSONDecodeError, AttributeError):
                    print(f"\n--- OUTPUT ---\n{cr.output[:400]}\n")


if __name__ == "__main__":
    asyncio.run(main())
