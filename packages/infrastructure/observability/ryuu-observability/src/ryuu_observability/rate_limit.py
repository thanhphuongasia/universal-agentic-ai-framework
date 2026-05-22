"""Back-compat shim. Canonical: `ryuu_observability_core.rate_limit`."""
from ryuu_observability_core.rate_limit import RateLimiter, RatePolicy
__all__ = ["RateLimiter", "RatePolicy"]
