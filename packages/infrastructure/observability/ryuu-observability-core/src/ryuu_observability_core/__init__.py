"""ryuu-observability-core — In-process observability primitives.

Cost tracking, audit logging (JSONL hash chain), rate limiting. Zero external
SDK dependencies. For distributed tracing with OpenTelemetry, install the
sibling `ryuu-observability-otel` package.
"""

from ryuu_observability_core.audit import (
    AuditConfig,
    AuditEvent,
    AuditLogger,
    verify_chain,
)
from ryuu_observability_core.cost import (
    CostPolicy,
    CostTracker,
    ICostStore,
    UsageSnapshot,
)
from ryuu_observability_core.rate_limit import RateLimiter, RatePolicy

__version__ = "0.3.0a1"

__all__ = [
    "AuditConfig",
    "AuditEvent",
    "AuditLogger",
    "verify_chain",
    "CostPolicy",
    "CostTracker",
    "ICostStore",
    "UsageSnapshot",
    "RateLimiter",
    "RatePolicy",
]
