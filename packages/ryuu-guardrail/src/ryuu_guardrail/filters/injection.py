from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ryuu_guardrail.protocol import GuardrailAction, GuardrailResult

if TYPE_CHECKING:
    from ryuu_core.context import ExecutionContext

_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions?", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?previous\s+instructions?", re.IGNORECASE),
    re.compile(r"forget\s+(everything|all)\s+above", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(?:a|an|in\s+developer\s+mode)", re.IGNORECASE),
    re.compile(r"\bjailbreak\b", re.IGNORECASE),
    re.compile(r"\bDAN\s+mode\b", re.IGNORECASE),
    re.compile(r"act\s+as\s+if\s+you\s+(have\s+no\s+restrictions|are\s+not\s+an?\s+ai)", re.IGNORECASE),
]


class PromptInjectionDetector:
    guardrail_id = "prompt-injection-detector"
    applies_to = "input"

    def __init__(self, extra_patterns: list[str] | None = None) -> None:
        self._patterns = list(_INJECTION_PATTERNS)
        if extra_patterns:
            self._patterns.extend(re.compile(p, re.IGNORECASE) for p in extra_patterns)

    async def check(self, content: str, ctx: ExecutionContext) -> GuardrailResult:
        for pattern in self._patterns:
            if pattern.search(content):
                return GuardrailResult(
                    passed=False,
                    action=GuardrailAction.BLOCK,
                    reason=f"Prompt injection detected",
                )
        return GuardrailResult(passed=True, action=GuardrailAction.PASS)
