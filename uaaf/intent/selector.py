"""StrategySelector — P1-T03."""

from __future__ import annotations

from uaaf.cognitive.strategy import ICognitiveStrategy
from uaaf.intent.models import StructuredIntent
from uaaf_workflow.context import ExecutionContext


class StrategySelector:
    """Selects the first applicable ICognitiveStrategy for a given intent."""

    def __init__(self, strategies: list[ICognitiveStrategy]) -> None:
        self._strategies = strategies

    def select(self, intent: StructuredIntent, context: ExecutionContext) -> ICognitiveStrategy:
        for strategy in self._strategies:
            if strategy.applicable(intent, context):
                return strategy
        raise ValueError(
            f"No applicable strategy found for intent_type={intent.intent_type!r} "
            f"complexity={intent.complexity.name}"
        )
