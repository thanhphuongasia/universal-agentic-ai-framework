"""Todo-domain intent analyzers — two implementations of IIntentAnalyzer.

  TodoIntentAnalyzer    — rule-based, keyword matching, no LLM call (fast, free)
  build_llm_analyzer()  — factory returning LLMIntentAnalyzer with a todo-specific
                          system prompt (slower, costs tokens, handles ambiguity)

Both produce StructuredIntent with entities["prompt_name"] populated, so they
are drop-in interchangeable in TodoDirectStrategy.
"""

from __future__ import annotations

import os as _os
from dataclasses import dataclass
from typing import Any

from ryuu.intent.llm_analyzer import LLMIntentAnalyzer
from ryuu.intent.models import (
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
_PER_ENTITY_KEYWORDS = frozenset({
    "each goal", "every goal", "separately", "individually", "per-goal",
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

        # Common: detect per-entity scope (used by Parallel strategy)
        per_entity = any(kw in msg for kw in _PER_ENTITY_KEYWORDS)

        if any(kw in msg for kw in _REPORT_KEYWORDS):
            entities = {"prompt_name": "priority_breakdown"}
            if per_entity:
                entities["scope"] = "per_entity"
            return StructuredIntent(
                intent_type="report",
                action=message,
                entities=entities,
                complexity=ComplexityLevel.LOW,
                confidence=0.9,
                suggested_strategy=DIRECT,
                suggested_model_tier=ModelTier.CHEAP,
            )

        if any(kw in msg for kw in _PLANNING_KEYWORDS):
            entities = {"prompt_name": "next_sprint"}
            if per_entity:
                entities["scope"] = "per_entity"
            return StructuredIntent(
                intent_type="planning",
                action=message,
                entities=entities,
                complexity=ComplexityLevel.HIGH,
                confidence=0.85,
                suggested_strategy=REACT,
                suggested_model_tier=ModelTier.STANDARD,
            )

        # Default: general analysis
        entities = {"prompt_name": "analyze"}
        if per_entity:
            entities["scope"] = "per_entity"
        return StructuredIntent(
            intent_type="analysis",
            action=message,
            entities=entities,
            complexity=ComplexityLevel.MEDIUM,
            confidence=0.80,
            suggested_strategy=DIRECT,
            suggested_model_tier=ModelTier.STANDARD,
        )


# ---------------------------------------------------------------------------
# LLM-backed analyzer — uses ryuu.intent.LLMIntentAnalyzer with todo prompt
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
  AND MAY contain "scope":
    "per_entity"         — set if user wants per-goal / per-task analysis
                           (keywords: each, every, separately, individually)
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

  "Analyze each goal separately" →
    {"intent_type":"analysis","action":"analyze","entities":{"prompt_name":"analyze","scope":"per_entity"},
     "complexity":"HIGH","confidence":0.9,"ambiguous":false,"clarification_questions":[],
     "suggested_strategy":"direct","suggested_model_tier":"standard"}

Respond with ONLY the JSON object — no prose, no markdown.
"""


def build_llm_analyzer(
    provider: Any | None = None,
    model: str = "gpt-4o-mini",
) -> LLMIntentAnalyzer:
    """Factory: LLMIntentAnalyzer wired with the todo-domain system prompt.

    Requires a real LLM — raises RuntimeError if `provider` is not given AND
    OPENAI_API_KEY is not set. No fake fallback: LLM analyzer is meaningless
    without a real classifier; use ANALYZER_MODE='rule' for offline runs.
    """
    if provider is None:
        api_key = _os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "LLM analyzer requires OPENAI_API_KEY. "
                "Set the env var, or use ANALYZER_MODE='rule' / CLI 'rule' for offline runs."
            )
        from ryuu.providers.adapters.openai import OpenAIProvider
        provider = OpenAIProvider(api_key=api_key)

    return LLMIntentAnalyzer(
        provider=provider,
        model=model,
        system_prompt=TODO_INTENT_SYSTEM_PROMPT,
    )
