"""IVerifier Protocol and VerificationResult — Phase 2 (moved from strategy.py)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from uaaf.runtime.context import ExecutionContext


@dataclass(frozen=True)
class VerificationResult:
    """Result from IVerifier.verify()."""

    passed: bool
    confidence: float  # 0.0–1.0
    feedback: str = ""


@runtime_checkable
class IVerifier(Protocol):
    """Judges whether a strategy's output is acceptable."""

    verifier_id: str

    async def verify(
        self,
        output: str,
        context: ExecutionContext,
        metadata: dict[str, Any] | None = None,
    ) -> VerificationResult: ...
