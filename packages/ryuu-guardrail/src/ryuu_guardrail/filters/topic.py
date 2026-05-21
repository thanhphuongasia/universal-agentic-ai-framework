from __future__ import annotations

from typing import TYPE_CHECKING

from ryuu_guardrail.protocol import GuardrailAction, GuardrailResult

if TYPE_CHECKING:
    from ryuu_core.context import ExecutionContext


class TopicBlocker:
    guardrail_id = "topic-blocker"
    applies_to = "both"

    def __init__(self, denied_topics: list[str] | None = None) -> None:
        self._denied = [t.lower() for t in (denied_topics or [])]

    async def check(self, content: str, ctx: ExecutionContext) -> GuardrailResult:
        lower = content.lower()
        for topic in self._denied:
            if topic in lower:
                return GuardrailResult(
                    passed=False,
                    action=GuardrailAction.BLOCK,
                    reason=f"Topic blocked: '{topic}'",
                )
        return GuardrailResult(passed=True, action=GuardrailAction.PASS)
