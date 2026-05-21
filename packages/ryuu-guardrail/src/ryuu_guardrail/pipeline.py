from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from ryuu_guardrail.passthrough import PassthroughGuardrail
from ryuu_guardrail.protocol import GuardrailAction, GuardrailBlockedError, GuardrailResult, IGuardrail

if TYPE_CHECKING:
    from ryuu_core.context import ExecutionContext


class TrustLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class GuardrailPipeline:
    """Runs guardrails sequentially. BLOCK raises GuardrailBlockedError immediately."""

    def __init__(self, guardrails: list[IGuardrail]) -> None:
        self.guardrails = guardrails

    async def check(self, content: str, ctx: ExecutionContext) -> GuardrailResult:
        current_content = content
        last: GuardrailResult = GuardrailResult(passed=True, action=GuardrailAction.PASS)

        for g in self.guardrails:
            result = await g.check(current_content, ctx)
            if result.action == GuardrailAction.BLOCK:
                raise GuardrailBlockedError(g.guardrail_id, result.reason)
            if result.action == GuardrailAction.REDACT:
                current_content = result.redacted_content
            last = result

        if current_content != content:
            return GuardrailResult(
                passed=True,
                action=GuardrailAction.REDACT,
                redacted_content=current_content,
            )
        return last

    @classmethod
    def for_trust_level(cls, level: TrustLevel) -> GuardrailPipeline:
        from ryuu_guardrail.filters.injection import PromptInjectionDetector
        from ryuu_guardrail.filters.pii import PIIFilter
        from ryuu_guardrail.filters.topic import TopicBlocker

        if level == TrustLevel.LOW:
            return cls([PassthroughGuardrail()])
        if level == TrustLevel.MEDIUM:
            return cls([PromptInjectionDetector(), PIIFilter()])
        return cls([
            PromptInjectionDetector(),
            PIIFilter(),
            TopicBlocker(),
        ])
