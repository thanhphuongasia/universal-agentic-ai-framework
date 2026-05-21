"""Core domain models — zero stdlib-only, no external deps."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any

# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Cost:
    """Immutable record of LLM call cost."""

    input_tokens: int
    output_tokens: int
    usd: float
    provider: str
    model: str

    @classmethod
    def zero(cls, provider: str = "unknown", model: str = "unknown") -> Cost:
        return cls(input_tokens=0, output_tokens=0, usd=0.0, provider=provider, model=model)


# ---------------------------------------------------------------------------
# Agent execution models
# ---------------------------------------------------------------------------


@dataclass
class Task:
    """Unit of work dispatched to an agent."""

    task_id: str
    payload: dict[str, Any]
    estimated_cost: Cost | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    """Return value from a completed agent execution."""

    task_id: str
    output: Any
    cost: Cost
    success: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Intent / cognitive models
# ---------------------------------------------------------------------------

StrategyId = str

DIRECT: StrategyId = "direct"
REACT: StrategyId = "react"
EVALUATOR_OPTIMIZER: StrategyId = "evaluator_optimizer"
PARALLEL_FANOUT: StrategyId = "parallel_fanout"


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


@dataclass(frozen=True)
class StructuredIntent:
    """Parsed, structured representation of a user request."""

    intent_type: str
    action: str
    entities: dict[str, Any]
    complexity: ComplexityLevel
    confidence: float

    ambiguous: bool = False
    clarification_questions: list[str] = field(default_factory=list)
    suggested_strategy: StrategyId = DIRECT
    suggested_model_tier: ModelTier = ModelTier.STANDARD


@dataclass(frozen=True)
class CognitiveResult:
    """Output produced by an ICognitiveStrategy.execute() call."""

    content: str
    confidence: float

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
