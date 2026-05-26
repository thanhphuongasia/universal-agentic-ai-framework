from __future__ import annotations

import asyncio
import time
import uuid
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
        self.run_id = uuid.uuid4().hex
        self.model: str | None = getattr(target, "model", None)
        self._target = target
        self._scorers = scorers
        self._budget_usd = budget_usd
        self._refine_logger = refine_logger
        self._cancel_event = asyncio.Event()
        self._last_suite: SuiteResult | None = None
        # If target exposes set_refine_logger() (duck-typed), inject so its
        # internal Evaluator auto-logs during run.
        if refine_logger is not None and hasattr(target, "set_refine_logger"):
            target.set_refine_logger(refine_logger)

    def cancel(self) -> None:
        """Request graceful cancellation. Streaming run will stop between cases."""
        self._cancel_event.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel_event.is_set()

    @property
    def last_suite_result(self) -> SuiteResult | None:
        """SuiteResult from the most recent run/stream — None if never run."""
        return self._last_suite

    # ------------------------------------------------------------------
    # Sync mode — collect entire SuiteResult before returning
    # ------------------------------------------------------------------

    async def run(self, cases: list[EvalCase]) -> SuiteResult:
        suite = SuiteResult(suite_id=self.suite_id, run_id=self.run_id)
        for case in cases:
            if self._cancel_event.is_set():
                break
            result = await self._run_case(case)
            suite.cases.append(result)
            suite.total_cost_usd += result.cost_usd
            if self._budget_usd is not None and suite.total_cost_usd >= self._budget_usd:
                break
        self._last_suite = suite
        return suite

    # ------------------------------------------------------------------
    # Streaming mode — yield ProgressEvent for live SSE / UI updates
    # ------------------------------------------------------------------

    async def stream(
        self,
        cases: list[EvalCase],
        *,
        concurrency: int = 1,
    ) -> AsyncIterator[ProgressEvent]:
        """Yield ProgressEvent per stage: suite_start, case_*, suite_done.

        concurrency: when 1, cases run sequentially (events arrive in order).
        When >1, up to N cases run in parallel via asyncio.Semaphore — events
        per case are still emitted as a coherent block (case_start … case_done)
        but case blocks from different cases may interleave.

        Errors emit ``type="error"`` events but stream continues unless
        budget exhausted.
        """
        suite = SuiteResult(suite_id=self.suite_id, run_id=self.run_id)
        yield ProgressEvent(
            type="suite_start",
            payload={
                "suite_id": self.suite_id,
                "run_id": self.run_id,
                "total_cases": len(cases),
                "concurrency": concurrency,
            },
        )

        if concurrency <= 1 or len(cases) <= 1:
            async for ev in self._stream_sequential(cases, suite):
                yield ev
        else:
            async for ev in self._stream_parallel(cases, suite, concurrency):
                yield ev

        self._last_suite = suite
        yield ProgressEvent(
            type="suite_done",
            payload={
                "run_id": self.run_id,
                "pass_rate": suite.pass_rate,
                "passed_count": suite.passed_count,
                "total_count": suite.total_count,
                "total_cost_usd": suite.total_cost_usd,
                "cancelled": self._cancel_event.is_set(),
            },
        )

    # ------------------------------------------------------------------
    # Internal — sequential & parallel stream loops
    # ------------------------------------------------------------------

    def _case_done_payload(self, result: CaseResult) -> dict:
        return {
            "passed": result.passed,
            "scores": [
                {"scorer_id": s.scorer_id, "score": s.score, "passed": s.passed,
                 "reason": s.reason}
                for s in result.scores
            ],
            "latency_ms": result.latency_ms,
            "cost_usd": result.cost_usd,
        }

    async def _stream_sequential(
        self, cases: list[EvalCase], suite: SuiteResult,
    ) -> AsyncIterator[ProgressEvent]:
        total = len(cases)
        for idx, case in enumerate(cases):
            if self._cancel_event.is_set():
                yield ProgressEvent(
                    type="error",
                    payload={"error_type": "cancelled", "message": "run cancelled by user"},
                )
                break
            yield ProgressEvent(
                type="case_start", case_id=case.case_id,
                payload={"index": idx, "total": total},
            )
            model_hint = self.model or case.metadata.get("model")
            yield ProgressEvent(
                type="llm_attempt", case_id=case.case_id,
                payload={"attempt": 1, "model": model_hint},
            )
            result = await self._run_case(case)
            suite.cases.append(result)
            suite.total_cost_usd += result.cost_usd
            yield ProgressEvent(
                type="llm_done", case_id=case.case_id,
                payload={"latency_ms": result.latency_ms, "cost_usd": result.cost_usd},
            )
            if result.refine_count > 0:
                yield ProgressEvent(
                    type="refine_done", case_id=case.case_id,
                    payload={
                        "refine_count": result.refine_count,
                        "feedback_history": result.refine_feedback_history,
                        "passed": result.passed,
                    },
                )
            if result.error:
                yield ProgressEvent(
                    type="error", case_id=case.case_id,
                    payload={"error_type": "runtime", "message": result.error},
                )
            yield ProgressEvent(
                type="case_done", case_id=case.case_id,
                payload=self._case_done_payload(result),
            )
            if self._budget_usd is not None and suite.total_cost_usd >= self._budget_usd:
                yield ProgressEvent(
                    type="error",
                    payload={"error_type": "budget_exceeded",
                             "message": f"budget ${self._budget_usd:.2f} reached"},
                )
                break

    async def _stream_parallel(
        self,
        cases: list[EvalCase],
        suite: SuiteResult,
        concurrency: int,
    ) -> AsyncIterator[ProgressEvent]:
        """Run up to N cases concurrently via Semaphore. Workers push events
        into a queue; the generator drains the queue and yields. Case blocks
        for different cases may interleave but events within one case stay
        ordered."""
        sem = asyncio.Semaphore(concurrency)
        queue: asyncio.Queue[ProgressEvent | None] = asyncio.Queue()
        total = len(cases)

        async def worker(idx: int, case: EvalCase) -> None:
            async with sem:
                if self._cancel_event.is_set():
                    return
                await queue.put(ProgressEvent(
                    type="case_start", case_id=case.case_id,
                    payload={"index": idx, "total": total},
                ))
                model_hint = self.model or case.metadata.get("model")
                await queue.put(ProgressEvent(
                    type="llm_attempt", case_id=case.case_id,
                    payload={"attempt": 1, "model": model_hint},
                ))
                result = await self._run_case(case)
                # asyncio is single-threaded — appending to suite is safe between awaits
                suite.cases.append(result)
                suite.total_cost_usd += result.cost_usd
                await queue.put(ProgressEvent(
                    type="llm_done", case_id=case.case_id,
                    payload={"latency_ms": result.latency_ms, "cost_usd": result.cost_usd},
                ))
                if result.refine_count > 0:
                    await queue.put(ProgressEvent(
                        type="refine_done", case_id=case.case_id,
                        payload={
                            "refine_count": result.refine_count,
                            "feedback_history": result.refine_feedback_history,
                            "passed": result.passed,
                        },
                    ))
                if result.error:
                    await queue.put(ProgressEvent(
                        type="error", case_id=case.case_id,
                        payload={"error_type": "runtime", "message": result.error},
                    ))
                await queue.put(ProgressEvent(
                    type="case_done", case_id=case.case_id,
                    payload=self._case_done_payload(result),
                ))

        tasks = [asyncio.create_task(worker(i, c)) for i, c in enumerate(cases)]

        async def waiter() -> None:
            await asyncio.gather(*tasks, return_exceptions=True)
            await queue.put(None)  # sentinel

        wait_task = asyncio.create_task(waiter())

        while True:
            ev = await queue.get()
            if ev is None:
                break
            yield ev

        await wait_task

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
