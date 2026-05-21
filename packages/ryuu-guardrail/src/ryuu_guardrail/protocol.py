from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable

from ryuu_core.context import ExecutionContext
from ryuu_core.errors import FrameworkError


class GuardrailAction(StrEnum):
    PASS = "pass"
    BLOCK = "block"
    REDACT = "redact"
    WARN = "warn"


@dataclass(frozen=True)
class GuardrailResult:
    passed: bool
    action: GuardrailAction
    reason: str = ""
    redacted_content: str = ""


class GuardrailBlockedError(FrameworkError):
    def __init__(self, guardrail_id: str, reason: str) -> None:
        super().__init__(f"[{guardrail_id}] {reason}")
        self.guardrail_id = guardrail_id
        self.reason = reason


@runtime_checkable
class IGuardrail(Protocol):
    guardrail_id: str
    applies_to: Literal["input", "output", "both"]

    async def check(self, content: str, ctx: ExecutionContext) -> GuardrailResult: ...
