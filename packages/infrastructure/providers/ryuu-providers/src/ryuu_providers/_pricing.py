"""Back-compat shim. Canonical source: `ryuu_providers_core._pricing`.

``PRICING`` / ``CONTEXT_WINDOW`` are mutable module globals that ``reload_pricing()``
rebuilds. Forward attribute access to the canonical module via ``__getattr__`` so
they always reflect live state — a static ``from ... import PRICING`` would freeze
a stale dict and reloads wouldn't propagate through this shim.
"""

import ryuu_providers_core._pricing as _src
from ryuu_providers_core._pricing import (  # noqa: F401 — functions are stable refs
    _resolve_pricing_file,
    calculate_usd,
    reload_pricing,
)


def __getattr__(name: str) -> object:
    return getattr(_src, name)


__all__ = [
    "CONTEXT_WINDOW",
    "PRICING",
    "_resolve_pricing_file",
    "calculate_usd",
    "reload_pricing",
]
