"""Todo-domain intent analyzers — two implementations of IIntentAnalyzer.

  TodoIntentAnalyzer    — rule-based, keyword matching, no LLM call (fast, free)
  build_llm_analyzer()  — factory returning LLMIntentAnalyzer with a todo-specific
                          system prompt (slower, costs tokens, handles ambiguity)

Both produce StructuredIntent with entities["prompt_name"] populated, so they
are drop-in interchangeable in TodoDirectStrategy.
"""

from __future__ import annotations

import json as _json
import os as _os
from dataclasses import dataclass
from typing import Any

from uaaf.intent.llm_analyzer import LLMIntentAnalyzer
from uaaf.intent.models import (
    DIRECT,
    REACT,
    ComplexityLevel,
    ModelTier,
    StructuredIntent,
)

# Keyword sets for each intent tier
_REPORT_KEYWORDS = frozenset({
    "breakdown", "json", "split", "by priority", "per goal",
    "stats", "distribution", "percentage", "count",
})
_PLANNING_KEYWORDS = frozenset({
    "next sprint", "focus", "prioritize", "what should", "recommend",
    "plan", "schedule", "roadmap", "maximize",
})


@dataclass
class TodoIntentAnalyzer:
    """Rule-based IIntentAnalyzer for todo domain queries.

    Maps message keywords → StructuredIntent with:
      - intent_type  : "report" | "planning" | "analysis"
      - prompt_name  : stored in entities["prompt_name"] so strategy can
                       pick the right YAML prompt template automatically
      - complexity   : drives model tier selection (LOW → cheap, HIGH → standard)
      - strategy     : DIRECT for single-pass, REACT for multi-step planning
    """

    async def analyze(
        self,
        message: str,
        scope_key: str,
        history: list[dict[str, str]] | None = None,
    ) -> StructuredIntent:
        msg = message.lower()

        if any(kw in msg for kw in _REPORT_KEYWORDS):
            return StructuredIntent(
                intent_type="report",
                action=message,
                entities={"prompt_name": "priority_breakdown"},
                complexity=ComplexityLevel.LOW,
                confidence=0.9,
                suggested_strategy=DIRECT,
                suggested_model_tier=ModelTier.CHEAP,
            )

        if any(kw in msg for kw in _PLANNING_KEYWORDS):
            return StructuredIntent(
                intent_type="planning",
                action=message,
                entities={"prompt_name": "next_sprint"},
                complexity=ComplexityLevel.HIGH,
                confidence=0.85,
                suggested_strategy=REACT,
                suggested_model_tier=ModelTier.STANDARD,
            )

        # Default: general analysis
        return StructuredIntent(
            intent_type="analysis",
            action=message,
            entities={"prompt_name": "analyze"},
            complexity=ComplexityLevel.MEDIUM,
            confidence=0.80,
            suggested_strategy=DIRECT,
            suggested_model_tier=ModelTier.STANDARD,
        )


# ---------------------------------------------------------------------------
# LLM-backed analyzer — uses uaaf.intent.LLMIntentAnalyzer with todo prompt
# ---------------------------------------------------------------------------

TODO_INTENT_SYSTEM_PROMPT = """\
You classify user messages for a todo/goal management app. Return JSON ONLY.

Required JSON fields:
- intent_type: "report" | "planning" | "analysis"
- action: short verb-noun describing what user wants
- entities: object — MUST contain "prompt_name", one of:
    "priority_breakdown" — for stats / JSON / by-priority queries
    "next_sprint"        — for planning / forward-looking queries
    "analyze"            — default / general analysis
- complexity: "LOW" | "MEDIUM" | "HIGH"
- confidence: 0.0-1.0
- ambiguous: boolean
- clarification_questions: list (empty unless ambiguous=true)
- suggested_strategy: "direct" | "react"
- suggested_model_tier: "cheap" | "standard" | "powerful"

Examples:
  "Show task counts by priority" →
    {"intent_type":"report","action":"show stats","entities":{"prompt_name":"priority_breakdown"},
     "complexity":"LOW","confidence":0.95,"ambiguous":false,"clarification_questions":[],
     "suggested_strategy":"direct","suggested_model_tier":"cheap"}

  "What should I focus on next sprint?" →
    {"intent_type":"planning","action":"plan sprint","entities":{"prompt_name":"next_sprint"},
     "complexity":"HIGH","confidence":0.9,"ambiguous":false,"clarification_questions":[],
     "suggested_strategy":"react","suggested_model_tier":"standard"}

  "Analyze my goals progress" →
    {"intent_type":"analysis","action":"analyze","entities":{"prompt_name":"analyze"},
     "complexity":"MEDIUM","confidence":0.85,"ambiguous":false,"clarification_questions":[],
     "suggested_strategy":"direct","suggested_model_tier":"standard"}

Respond with ONLY the JSON object — no prose, no markdown.
"""


def _fake_intent_provider() -> Any:
    """Demo-mode provider: cycles through valid intent JSON for each preset.

    Real OpenAI provider used when OPENAI_API_KEY is set; this fallback
    keeps demo runs working without an API key.
    """
    from uaaf._testing.fakes import FakeLLMProvider
    from uaaf.providers.llm import Response, TokenUsage

    def _resp(intent_type: str, prompt_name: str, complexity: str) -> Response:
        return Response(
            content=_json.dumps({
                "intent_type": intent_type,
                "action": "demo",
                "entities": {"prompt_name": prompt_name},
                "complexity": complexity,
                "confidence": 0.9,
                "ambiguous": False,
                "clarification_questions": [],
                "suggested_strategy": "direct",
                "suggested_model_tier": "standard",
            }),
            model="fake",
            usage=TokenUsage(40, 30),
            finish_reason="stop",
        )

    # 4 cycles × 3 types = 12 responses — enough for "all presets" + several iterations
    cycle = [
        _resp("report",   "priority_breakdown", "LOW"),
        _resp("analysis", "analyze",            "MEDIUM"),
        _resp("planning", "next_sprint",        "HIGH"),
    ]
    return FakeLLMProvider(responses=cycle * 4)


def build_llm_analyzer(
    provider: Any | None = None,
    model: str = "gpt-4o-mini",
) -> LLMIntentAnalyzer:
    """Factory: LLMIntentAnalyzer wired with the todo-domain system prompt.

    If `provider` not given:
      - OPENAI_API_KEY set → real OpenAIProvider
      - otherwise          → FakeLLMProvider that emits valid intent JSON
    """
    if provider is None:
        api_key = _os.getenv("OPENAI_API_KEY")
        if api_key:
            from uaaf.providers.adapters.openai import OpenAIProvider
            provider = OpenAIProvider(api_key=api_key)
        else:
            provider = _fake_intent_provider()

    return LLMIntentAnalyzer(
        provider=provider,
        model=model,
        system_prompt=TODO_INTENT_SYSTEM_PROMPT,
    )
