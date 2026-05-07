"""LLMIntentAnalyzer — LLM-backed IIntentAnalyzer — P1-T07."""

from __future__ import annotations

import json
import re
from typing import Any

from uaaf.intent.models import (
    DIRECT,
    ComplexityLevel,
    ModelTier,
    StructuredIntent,
)
from uaaf.providers.llm import CompletionRequest, Message

INTENT_SYSTEM_PROMPT = """\
You are an intent classification system. Given a user message, output a JSON object with these fields:
- intent_type: string (e.g. "query", "analysis", "synthesis", "command", "unknown")
- action: string describing the specific action (e.g. "search", "dependency_analysis")
- entities: object with relevant named entities extracted from the message
- complexity: one of "LOW", "MEDIUM", "HIGH"
- confidence: float 0.0-1.0 representing your confidence
- ambiguous: boolean — true if the request is unclear
- clarification_questions: list of strings (non-empty only when ambiguous=true)
- suggested_strategy: one of "direct", "react", "evaluator_optimizer"
- suggested_model_tier: one of "cheap", "standard", "powerful"

Respond with ONLY the JSON object, no prose. Example:
{"intent_type":"query","action":"search","entities":{},"complexity":"LOW","confidence":0.95,\
"ambiguous":false,"clarification_questions":[],"suggested_strategy":"direct","suggested_model_tier":"standard"}
"""

_FALLBACK_INTENT = StructuredIntent(
    intent_type="unknown",
    action="clarify",
    entities={},
    complexity=ComplexityLevel.LOW,
    confidence=0.3,
    ambiguous=True,
    clarification_questions=["Could you clarify your request?"],
    suggested_strategy=DIRECT,
    suggested_model_tier=ModelTier.STANDARD,
)

_COMPLEXITY_MAP = {
    "LOW": ComplexityLevel.LOW,
    "MEDIUM": ComplexityLevel.MEDIUM,
    "HIGH": ComplexityLevel.HIGH,
}

_TIER_MAP = {
    "cheap": ModelTier.CHEAP,
    "standard": ModelTier.STANDARD,
    "powerful": ModelTier.POWERFUL,
}


def _extract_json(text: str) -> dict[str, Any] | None:
    """Extract the first JSON object from text, even if wrapped in markdown."""
    result: dict[str, Any]
    # Try direct parse first.
    try:
        result = json.loads(text.strip())
        return result
    except json.JSONDecodeError:
        pass
    # Try to find JSON block inside ```...```
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(1))
            return result
        except json.JSONDecodeError:
            pass
    # Try to find any {...} block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(0))
            return result
        except json.JSONDecodeError:
            pass
    return None


def _parse_intent(data: dict[str, Any]) -> StructuredIntent:
    """Build StructuredIntent from a parsed JSON dict. Raises KeyError on missing fields."""
    return StructuredIntent(
        intent_type=data["intent_type"],
        action=data["action"],
        entities=data.get("entities", {}),
        complexity=_COMPLEXITY_MAP.get(data["complexity"], ComplexityLevel.LOW),
        confidence=float(data["confidence"]),
        ambiguous=bool(data.get("ambiguous", False)),
        clarification_questions=list(data.get("clarification_questions", [])),
        suggested_strategy=str(data.get("suggested_strategy", DIRECT)),
        suggested_model_tier=_TIER_MAP.get(
            str(data.get("suggested_model_tier", "standard")), ModelTier.STANDARD
        ),
    )


class LLMIntentAnalyzer:
    """Analyzes user messages by asking an LLM for structured intent JSON."""

    def __init__(
        self,
        provider: Any,  # ILLMProvider — Any to avoid circular Protocol import at runtime
        model: str | None = None,
        system_prompt: str | None = None,
    ) -> None:
        self._provider = provider
        self._model = model
        self._system_prompt = system_prompt or INTENT_SYSTEM_PROMPT

    async def analyze(
        self,
        message: str,
        scope_key: str,
        history: list[dict[str, str]] | None = None,
    ) -> StructuredIntent:
        messages = [Message(role="user", content=message)]
        if history:
            # Prepend recent history (last 5 turns) for context.
            history_messages = [
                Message(role=h["role"], content=h["content"]) for h in history[-5:]
            ]
            messages = history_messages + messages

        request = CompletionRequest(
            messages=messages,
            system=self._system_prompt,
            model=self._model or "gpt-4o-mini",
            max_tokens=256,
            temperature=0.0,
        )
        response = await self._provider.complete(request)
        data = _extract_json(response.content)
        if data is None:
            return _FALLBACK_INTENT
        try:
            return _parse_intent(data)
        except (KeyError, ValueError):
            return _FALLBACK_INTENT
