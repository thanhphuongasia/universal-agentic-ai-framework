"""Intent tier models — P1-T01.

StructuredIntent is the common schema flowing from IIntentAnalyzer
to StrategySelector to ICognitiveStrategy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ComplexityLevel(IntEnum):
    """Estimated complexity of a request — drives strategy selection."""

    LOW = 1
    MEDIUM = 2
    HIGH = 3


class ModelTier(StrEnum):
    """Model capability tier suggested by the intent analyzer."""

    CHEAP = "cheap"
    STANDARD = "standard"
    POWERFUL = "powerful"

# ---------------------------------------------------------------------------
# StrategyId constants
# ---------------------------------------------------------------------------

StrategyId = str

DIRECT: StrategyId = "direct"
REACT: StrategyId = "react"
EVALUATOR_OPTIMIZER: StrategyId = "evaluator_optimizer"
PARALLEL_FANOUT: StrategyId = "parallel_fanout"

# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StructuredIntent:
    """Parsed, structured representation of a user request."""

    intent_type: str
    action: str
    entities: dict[str, Any]
    complexity: ComplexityLevel
    confidence: float  # 0.0–1.0

    ambiguous: bool = False
    clarification_questions: list[str] = field(default_factory=list)
    suggested_strategy: StrategyId = DIRECT
    suggested_model_tier: ModelTier = ModelTier.STANDARD


@dataclass(frozen=True)
class CognitiveResult:
    """Output produced by an ICognitiveStrategy.execute() call."""

    content: str
    confidence: float  # 0.0–1.0

    reasoning: str = ""
    evidence: list[Any] = field(default_factory=list)
    strategy_id: str = ""


@dataclass(frozen=True)
class CostEstimate:
    """Pre-execution cost estimate returned by ICognitiveStrategy.estimate_cost()."""

    input_tokens_est: int
    output_tokens_est: int
    usd_est: float
    steps_est: int = 1
