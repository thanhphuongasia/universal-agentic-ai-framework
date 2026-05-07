"""GroundTruthVerifier — compares output against a reference answer."""

from __future__ import annotations

from typing import Any, Literal

from uaaf.cognitive.verifier import VerificationResult
from uaaf.runtime.context import ExecutionContext


class GroundTruthVerifier:
    """Verifies output by comparing to a reference using exact, substring, or word-overlap modes."""

    verifier_id = "ground_truth"

    def __init__(
        self,
        reference: str,
        mode: Literal["exact", "substring", "word_overlap"] = "substring",
        threshold: float = 0.5,
    ) -> None:
        self._reference = reference
        self._mode = mode
        self._threshold = threshold

    async def verify(
        self,
        output: str,
        context: ExecutionContext,
        metadata: dict[str, Any] | None = None,
    ) -> VerificationResult:
        if self._mode == "exact":
            return self._exact(output)
        if self._mode == "substring":
            return self._substring(output)
        return self._word_overlap(output)

    def _exact(self, output: str) -> VerificationResult:
        passed = output.strip() == self._reference.strip()
        return VerificationResult(
            passed=passed,
            confidence=1.0 if passed else 0.0,
            feedback="" if passed else "Output does not exactly match reference",
        )

    def _substring(self, output: str) -> VerificationResult:
        passed = self._reference in output
        return VerificationResult(
            passed=passed,
            confidence=1.0 if passed else 0.0,
            feedback="" if passed else f"Reference not found in output: {self._reference!r}",
        )

    def _word_overlap(self, output: str) -> VerificationResult:
        ref_words = set(self._reference.lower().split())
        out_words = set(output.lower().split())
        if not ref_words and not out_words:
            return VerificationResult(passed=True, confidence=1.0)
        union = ref_words | out_words
        similarity = len(ref_words & out_words) / len(union) if union else 0.0
        passed = similarity >= self._threshold
        return VerificationResult(
            passed=passed,
            confidence=similarity,
            feedback="" if passed else f"Word overlap {similarity:.2f} below threshold {self._threshold}",
        )
