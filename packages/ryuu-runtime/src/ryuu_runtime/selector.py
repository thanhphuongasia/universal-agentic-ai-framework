"""StrategySelector — selects the first applicable ICognitiveStrategy."""

from __future__ import annotations

from ryuu_cognitive.strategy import ICognitiveStrategy
from ryuu_core.context import ExecutionContext
from ryuu_core.models import StructuredIntent


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
