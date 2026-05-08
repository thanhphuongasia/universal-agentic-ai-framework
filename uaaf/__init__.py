"""UAAF — Universal Agentic AI Framework."""

from __future__ import annotations

__version__ = "0.1.0b6"

from uaaf.execution.pool import AgentPool
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

__all__ = [
    "__version__",
    "AgentPool",
    "FrameworkError",
    "RetryableError",
    "DegradedError",
    "FatalError",
    "BudgetExceededError",
    "RateLimitTimeout",
    "retry_policy",
    "classify_external_error",
    "Tracer",
    "get_current_correlation_id",
]
