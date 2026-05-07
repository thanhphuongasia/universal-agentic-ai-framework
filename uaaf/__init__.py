"""UAAF — Universal Agentic AI Framework."""

from __future__ import annotations

__version__ = "0.1.0a1"

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
