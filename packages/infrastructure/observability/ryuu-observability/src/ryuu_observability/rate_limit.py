"""Back-compat shim. Canonical: `ryuu_observability_core.rate_limit`."""
from ryuu_observability_core.rate_limit import (
    IRateStore,
    InMemoryRateStore,
    RateLimiter,
    RatePolicy,
)
__all__ = ["IRateStore", "InMemoryRateStore", "RateLimiter", "RatePolicy"]
