"""UAAF — Universal Agentic AI Framework."""

from __future__ import annotations

__version__ = "0.1.0b7"

# Execution tier — most commonly needed in every agent implementation
from uaaf.execution.agent import AgentResult, BaseAgent, Task
from uaaf.execution.pool import AgentPool

# Intent models — needed when constructing StructuredIntent
from uaaf.intent.models import ComplexityLevel, ModelTier, StructuredIntent

# Observability
from uaaf.observability.cost import Cost
from uaaf.observability.errors import (
    BudgetExceededError,
    DegradedError,
    FatalError,
    FrameworkError,
    RateLimitTimeout,
    RetryableError,
    classify_external_error,
    retry_policy,
)
from uaaf.observability.tracer import Tracer, get_current_correlation_id

# Runtime — needed in every execute() signature
from uaaf.runtime.context import ContextScope, ExecutionContext

# Workflow engine
from uaaf.workflow.checkpoint import Checkpoint, ICheckpointStore
from uaaf.workflow.engine import IWorkflowEngine, WorkflowEngine, WorkflowResult, WorkflowStatus
from uaaf.workflow.state_machine import IState, StateMachine, StateTransition, Workflow
from uaaf.workflow.stores.file import FileCheckpointStore
from uaaf.workflow.stores.in_memory import InMemoryCheckpointStore

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
    "BudgetExceededError",
    "DegradedError",
    "FatalError",
    "FrameworkError",
    "RateLimitTimeout",
    "RetryableError",
    "classify_external_error",
    "retry_policy",
    "Tracer",
    "get_current_correlation_id",
    # Runtime
    "ContextScope",
    "ExecutionContext",
    # Workflow
    "Checkpoint",
    "ICheckpointStore",
    "IWorkflowEngine",
    "IState",
    "StateMachine",
    "StateTransition",
    "Workflow",
    "WorkflowEngine",
    "WorkflowResult",
    "WorkflowStatus",
    "FileCheckpointStore",
    "InMemoryCheckpointStore",
]
