"""VerifierPipeline — runs multiple IVerifiers with configurable pass logic."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from ryuu_cognitive.verifier import IVerifier, VerificationResult
from ryuu_core.context import ExecutionContext


class PipelineMode(StrEnum):
    ALL_PASS = "all_pass"
    ANY_PASS = "any_pass"
    THRESHOLD = "threshold"


class VerifierPipeline:
    """Runs a list of verifiers and aggregates results by mode."""

    verifier_id = "pipeline"

    def __init__(
        self,
        verifiers: list[IVerifier],
        mode: PipelineMode = PipelineMode.ALL_PASS,
        threshold_count: int = 1,
    ) -> None:
        self._verifiers = verifiers
        self._mode = mode
        self._threshold_count = threshold_count

    async def verify(
        self,
        output: str,
        context: ExecutionContext,
        metadata: dict[str, Any] | None = None,
    ) -> VerificationResult:
        if not self._verifiers:
            return VerificationResult(passed=True, confidence=1.0)

        results = [await v.verify(output, context, metadata) for v in self._verifiers]
        failed_feedbacks = [r.feedback for r in results if not r.passed and r.feedback]

        if self._mode == PipelineMode.ALL_PASS:
            passed = all(r.passed for r in results)
            confidence = min(r.confidence for r in results)
        elif self._mode == PipelineMode.ANY_PASS:
            passed = any(r.passed for r in results)
            confidence = max(r.confidence for r in results)
        else:  # THRESHOLD
            pass_count = sum(1 for r in results if r.passed)
            passed = pass_count >= self._threshold_count
            confidence = sum(r.confidence for r in results) / len(results)

        feedback = "; ".join(failed_feedbacks) if failed_feedbacks else ""
        return VerificationResult(passed=passed, confidence=confidence, feedback=feedback)
