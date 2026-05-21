from __future__ import annotations

from typing import TYPE_CHECKING

from ryuu_guardrail.protocol import GuardrailAction, GuardrailResult

if TYPE_CHECKING:
    from ryuu_core.context import ExecutionContext


class PassthroughGuardrail:
    """NullObject guardrail — passes everything, zero overhead."""

    guardrail_id = "passthrough"
    applies_to = "both"

    async def check(self, content: str, ctx: ExecutionContext) -> GuardrailResult:
        return GuardrailResult(passed=True, action=GuardrailAction.PASS)
