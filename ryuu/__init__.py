"""RYUU — Universal Agentic AI Framework."""

from __future__ import annotations

__version__ = "0.3.0a13"

# Factory facade (Phase 10 MVP) — lean single-agent + tool-calling
from ryuu.factory import Agent, StreamEvent

# Multi-agent facades (Phase 10.5 + 14.4)
from ryuu.facades import (
    Chain,
    Evaluator,
    FanOut,
    HierarchicalRouter,
    Orchestrator,
    Router,
)

# Batch processing (Phase 12 + 12.1)
from ryuu.batch import BatchAPIClient, BatchItem, BatchRunner, OpenAIBatchClient

# Prompt optimization (Phase 13)
from ryuu.prompt_optimizer import EvalCase, OptimizationResult, PromptOptimizer

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
    # Multi-agent facades (Phase 10.5 + 14.4)
    "Chain",
    "Evaluator",
    "FanOut",
    "HierarchicalRouter",
    "Orchestrator",
    "Router",
    # Batch (Phase 12 + 12.1)
    "BatchAPIClient",
    "BatchItem",
    "BatchRunner",
    "OpenAIBatchClient",
    # Prompt optimization (Phase 13)
    "EvalCase",
    "OptimizationResult",
    "PromptOptimizer",
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
