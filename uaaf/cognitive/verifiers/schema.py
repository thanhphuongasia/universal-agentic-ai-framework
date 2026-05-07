"""SchemaVerifier — validates output structure (JSON keys or raw substrings)."""

from __future__ import annotations

import json
from typing import Any

from uaaf.cognitive.verifier import VerificationResult
from uaaf.runtime.context import ExecutionContext


class SchemaVerifier:
    """Checks that required keys exist in JSON output (or substrings in raw output)."""

    verifier_id = "schema"

    def __init__(
        self,
        required_keys: list[str],
        output_must_be_json: bool = True,
    ) -> None:
        self._required_keys = required_keys
        self._output_must_be_json = output_must_be_json

    async def verify(
        self,
        output: str,
        context: ExecutionContext,
        metadata: dict[str, Any] | None = None,
    ) -> VerificationResult:
        if self._output_must_be_json:
            return self._verify_json(output)
        return self._verify_raw(output)

    def _verify_json(self, output: str) -> VerificationResult:
        try:
            parsed: dict[str, Any] = json.loads(output)
        except json.JSONDecodeError as exc:
            return VerificationResult(passed=False, confidence=0.0, feedback=f"Invalid JSON: {exc}")
        for key in self._required_keys:
            if key not in parsed:
                return VerificationResult(
                    passed=False, confidence=0.0, feedback=f"Missing required key: {key!r}"
                )
        return VerificationResult(passed=True, confidence=1.0)

    def _verify_raw(self, output: str) -> VerificationResult:
        for key in self._required_keys:
            if key not in output:
                return VerificationResult(
                    passed=False, confidence=0.0, feedback=f"Missing required substring: {key!r}"
                )
        return VerificationResult(passed=True, confidence=1.0)
