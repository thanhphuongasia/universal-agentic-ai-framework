from __future__ import annotations

from typing import Any

from ryuu_eval.models import SuiteResult


class ApiRenderer:
    def render(self, result: SuiteResult) -> dict[str, Any]:
        return {
            "suite_id": result.suite_id,
            "pass_rate": result.pass_rate,
            "passed_count": result.passed_count,
            "total_count": result.total_count,
            "total_cost_usd": result.total_cost_usd,
            "cases": [
                {
                    "case_id": cr.case.case_id,
                    "passed": cr.passed,
                    "output": cr.output,
                    "error": cr.error,
                    "cost_usd": cr.cost_usd,
                    "latency_ms": cr.latency_ms,
                    "scores": [
                        {
                            "scorer_id": s.scorer_id,
                            "score": s.score,
                            "passed": s.passed,
                            "reason": s.reason,
                        }
                        for s in cr.scores
                    ],
                }
                for cr in result.cases
            ],
        }
