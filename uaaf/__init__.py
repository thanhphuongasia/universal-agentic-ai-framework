"""UAAF — Universal Agentic AI Framework."""

from __future__ import annotations

__version__ = "0.2.0a1"

# Execution tier
from uaaf.execution.agent import AgentResult, BaseAgent, Task
from uaaf.execution.pool import AgentPool

# Intent models
from uaaf.intent.models import ComplexityLevel, ModelTier, StructuredIntent

# Observability
from uaaf.observability.cost import Cost
from uaaf.observability.tracer import Tracer, get_current_correlation_id

__all__ = [
    "__version__",
    # Execution
    "AgentPool",
    "AgentResult",
    "BaseAgent",
    "Task",
    # Intent
    "ComplexityLevel",
    "ModelTier",
    "StructuredIntent",
    # Observability
    "Cost",
    "Tracer",
    "get_current_correlation_id",
]
