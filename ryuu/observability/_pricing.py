# Backward-compat shim — canonical source is ryuu_providers._pricing
#
# Module-level __getattr__ ensures that mutable globals (PRICING, CONTEXT_WINDOW)
# always reflect the live state of the canonical module even after reload_pricing().
import ryuu_providers._pricing as _src
from ryuu_providers._pricing import (  # noqa: F401
    _resolve_pricing_file,
    calculate_usd,
    reload_pricing,
)


def __getattr__(name: str) -> object:
    return getattr(_src, name)
