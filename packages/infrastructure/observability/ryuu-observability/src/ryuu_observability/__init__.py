"""ryuu-observability — back-compat metapackage.

After Phase 8.13 the implementation lives in 2 sub-packages:
  • ryuu-observability-core   In-process: cost, audit, rate_limit (no SDK deps)
  • ryuu-observability-otel   OpenTelemetry tracer adapter

Old imports continue to work via shims. New code:
    from ryuu_observability_core import CostTracker, AuditLogger, RateLimiter
    from ryuu_observability_otel import Tracer, setup_tracing
"""

from ryuu_observability_core import (
    AuditConfig,
    AuditEvent,
    AuditLogger,
    CostPolicy,
    CostTracker,
    ICostStore,
    RateLimiter,
    RatePolicy,
    UsageSnapshot,
    verify_chain,
)

try:
    from ryuu_observability_otel import (
        Tracer,
        get_current_correlation_id,
        setup_tracing,
    )
except ImportError:
    # OTel sub-package not installed — tracing unavailable, other primitives OK
    Tracer = None  # type: ignore[assignment]
    get_current_correlation_id = None  # type: ignore[assignment]
    setup_tracing = None  # type: ignore[assignment]

__all__ = [
    "CostPolicy", "CostTracker", "ICostStore", "UsageSnapshot",
    "AuditConfig", "AuditEvent", "AuditLogger", "verify_chain",
    "Tracer", "get_current_correlation_id", "setup_tracing",
    "RateLimiter", "RatePolicy",
]
