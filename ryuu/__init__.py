"""RYUU — Universal Agentic AI Framework."""

from __future__ import annotations

__version__ = "0.3.0a8"

# Factory facade (Phase 10 MVP) — lean single-agent + tool-calling
from ryuu.factory import Agent, StreamEvent

# Multi-agent facades (Phase 10.5)
from ryuu.facades import Chain, Evaluator, FanOut, Orchestrator, Router

# Execution tier (class-based for advanced)
from ryuu.execution.agent import AgentResult, BaseAgent, Task
from ryuu.execution.pool import AgentPool

# Intent models
from ryuu.intent.models import ComplexityLevel, ModelTier, StructuredIntent

# Observability
from ryuu.observability.cost import Cost
from ryuu.observability.tracer import Tracer, get_current_correlation_id

__all__ = [
    "__version__",
    # Factory (Phase 10)
    "Agent",
    "StreamEvent",
    # Multi-agent facades (Phase 10.5)
    "Chain",
    "Evaluator",
    "FanOut",
    "Orchestrator",
    "Router",
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
