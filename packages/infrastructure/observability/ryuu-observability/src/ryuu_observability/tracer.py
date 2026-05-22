"""Back-compat shim. Canonical: `ryuu_observability_otel.tracer`.

Requires `ryuu-observability-otel` to be installed:
    pip install 'ryuu-observability[otel]'   # via extras
    pip install ryuu-observability-otel       # directly
"""
try:
    from ryuu_observability_otel.tracer import (
        Tracer,
        get_current_correlation_id,
        setup_tracing,
    )
except ImportError as e:
    raise ImportError(
        "Tracer requires `ryuu-observability-otel`. "
        "Install with: pip install 'ryuu-observability[otel]' or pip install ryuu-observability-otel"
    ) from e

__all__ = ["Tracer", "get_current_correlation_id", "setup_tracing"]
