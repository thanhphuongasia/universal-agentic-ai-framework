"""TodoIntentAnalyzer — keyword-based IIntentAnalyzer for the todo domain.

No LLM required — rule-based classification is sufficient for structured
todo queries. Replace with LLMIntentAnalyzer for open-ended / ambiguous input.
"""

from __future__ import annotations

from dataclasses import dataclass

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
