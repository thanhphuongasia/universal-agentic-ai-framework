from __future__ import annotations

import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING

from ryuu_eval_core.models import (
    CaseResult,
    EvalCase,
    ProgressEvent,
    SuiteResult,
)
from ryuu_eval_core.protocols import EvalTarget, Scorer

if TYPE_CHECKING:
    # Lazy import to avoid forcing ryuu dependency on lightweight eval-core users
    from ryuu.refine_logger import RefineLogger


class EvalRunner:
    """Eval orchestrator — sync ``run()`` OR streaming ``stream()``.

    Step 2 (Q1+Q3 decisions): ``stream()`` yields ProgressEvent for SSE.
    Step 3 (Q3 decision): optional ``refine_logger`` auto-captures Evaluator
    refine cycles when EvalTarget wraps a ryuu.Evaluator.
    """

    def __init__(
        self,
        suite_id: str,
        target: EvalTarget,
        scorers: list[Scorer],
        budget_usd: float | None = None,
        refine_logger: "RefineLogger | None" = None,
    ) -> None:
        self.suite_id = suite_id
        self._target = target
        self._scorers = scorers
        self._budget_usd = budget_usd
        self._refine_logger = refine_logger
        # If target exposes set_refine_logger() (duck-typed), inject so its
        # internal Evaluator auto-logs during run.
        if refine_logger is not None and hasattr(target, "set_refine_logger"):
            target.set_refine_logger(refine_logger)

    # ------------------------------------------------------------------
    # Sync mode — collect entire SuiteResult before returning
    # ------------------------------------------------------------------

    async def run(self, cases: list[EvalCase]) -> SuiteResult:
        suite = SuiteResult(suite_id=self.suite_id)
        for case in cases:
            result = await self._run_case(case)
            suite.cases.append(result)
            suite.total_cost_usd += result.cost_usd
            if self._budget_usd is not None and suite.total_cost_usd >= self._budget_usd:
                break
        return suite

    # ------------------------------------------------------------------
    # Streaming mode — yield ProgressEvent for live SSE / UI updates
    # ------------------------------------------------------------------

    async def stream(self, cases: list[EvalCase]) -> AsyncIterator[ProgressEvent]:
        """Yield ProgressEvent per stage: suite_start, case_*, suite_done.

        Consumers (HTTP SSE route, CLI reporter, test framework) format các
        events into their own output. Order guaranteed: suite_start → N×
        (case_start, llm_*, case_done) → suite_done.

        Errors emit ``type="error"`` events but stream continues unless
        budget exhausted.
        """
        suite = SuiteResult(suite_id=self.suite_id)
        yield ProgressEvent(
            type="suite_start",
            payload={"suite_id": self.suite_id, "total_cases": len(cases)},
        )

        for idx, case in enumerate(cases):
            yield ProgressEvent(
                type="case_start",
                case_id=case.case_id,
                payload={"index": idx, "total": len(cases)},
            )
            result = await self._run_case(case)
            suite.cases.append(result)
            suite.total_cost_usd += result.cost_usd

            # Surface refine info from logger (if target captured it)
            if result.refine_count > 0:
                yield ProgressEvent(
                    type="refine_done",
                    case_id=case.case_id,
                    payload={
                        "refine_count": result.refine_count,
                        "feedback_history": result.refine_feedback_history,
                        "passed": result.passed,
                    },
                )

            if result.error:
                yield ProgressEvent(
                    type="error",
                    case_id=case.case_id,
                    payload={"error_type": "runtime", "message": result.error},
                )
            yield ProgressEvent(
                type="case_done",
                case_id=case.case_id,
                payload={
                    "passed": result.passed,
                    "scores": [
                        {"scorer_id": s.scorer_id, "score": s.score, "passed": s.passed,
                         "reason": s.reason}
                        for s in result.scores
                    ],
                    "latency_ms": result.latency_ms,
                    "cost_usd": result.cost_usd,
                },
            )

            if self._budget_usd is not None and suite.total_cost_usd >= self._budget_usd:
                yield ProgressEvent(
                    type="error",
                    payload={"error_type": "budget_exceeded",
                             "message": f"budget ${self._budget_usd:.2f} reached"},
                )
                break

        yield ProgressEvent(
            type="suite_done",
            payload={
                "pass_rate": suite.pass_rate,
                "passed_count": suite.passed_count,
                "total_count": suite.total_count,
                "total_cost_usd": suite.total_cost_usd,
            },
        )

    # ------------------------------------------------------------------
    # Internal — execute one case
    # ------------------------------------------------------------------

    async def _run_case(self, case: EvalCase) -> CaseResult:
        t0 = time.monotonic()
        try:
            case_result = await self._target.run(case)
            case_result.latency_ms = (time.monotonic() - t0) * 1000
            case_result.scores = [await s.score(case, case_result.output) for s in self._scorers]
            # Pull refine info if target exposed last_refine_meta
            if hasattr(self._target, "last_refine_meta"):
                meta = self._target.last_refine_meta() or {}
                case_result.refine_count = int(meta.get("refine_count", 0))
                case_result.refine_feedback_history = list(meta.get("feedback_history", []))
            return case_result
        except Exception as exc:
            return CaseResult(
                case=case,
                output="",
                error=str(exc),
                latency_ms=(time.monotonic() - t0) * 1000,
            )
