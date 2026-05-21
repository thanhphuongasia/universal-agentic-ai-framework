from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ryuu_guardrail.protocol import GuardrailAction, GuardrailResult

if TYPE_CHECKING:
    from ryuu_core.context import ExecutionContext

_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"),
    "phone": re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})\b"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "cc": re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
}


class PIIFilter:
    guardrail_id = "pii-filter"
    applies_to = "both"

    def __init__(self, entity_types: list[str] | None = None) -> None:
        keys = entity_types or list(_PATTERNS.keys())
        self._patterns = {k: _PATTERNS[k] for k in keys if k in _PATTERNS}

    async def check(self, content: str, ctx: ExecutionContext) -> GuardrailResult:
        redacted = content
        found: list[str] = []
        for name, pattern in self._patterns.items():
            if pattern.search(redacted):
                found.append(name)
                redacted = pattern.sub("[REDACTED_PII]", redacted)

        if found:
            return GuardrailResult(
                passed=True,
                action=GuardrailAction.REDACT,
                reason=f"PII detected: {', '.join(found)}",
                redacted_content=redacted,
            )
        return GuardrailResult(passed=True, action=GuardrailAction.PASS)
