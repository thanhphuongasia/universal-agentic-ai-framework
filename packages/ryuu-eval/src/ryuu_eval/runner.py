from __future__ import annotations

import time

from ryuu_eval.models import CaseResult, EvalCase, SuiteResult
from ryuu_eval.protocols import EvalTarget, Scorer


class EvalRunner:
    def __init__(
        self,
        suite_id: str,
        target: EvalTarget,
        scorers: list[Scorer],
        budget_usd: float | None = None,
    ) -> None:
        self.suite_id = suite_id
        self._target = target
        self._scorers = scorers
        self._budget_usd = budget_usd

    async def run(self, cases: list[EvalCase]) -> SuiteResult:
        suite = SuiteResult(suite_id=self.suite_id)
        for case in cases:
            result = await self._run_case(case)
            suite.cases.append(result)
            suite.total_cost_usd += result.cost_usd
            if self._budget_usd is not None and suite.total_cost_usd >= self._budget_usd:
                break
        return suite

    async def _run_case(self, case: EvalCase) -> CaseResult:
        t0 = time.monotonic()
        try:
            case_result = await self._target.run(case)
            case_result.latency_ms = (time.monotonic() - t0) * 1000
            case_result.scores = [await s.score(case, case_result.output) for s in self._scorers]
            return case_result
        except Exception as exc:
            return CaseResult(
                case=case,
                output="",
                error=str(exc),
                latency_ms=(time.monotonic() - t0) * 1000,
            )
