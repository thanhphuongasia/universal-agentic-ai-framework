# Backward-compat shim — canonical source is ryuu_observability.tracer
from ryuu_observability.tracer import (  # noqa: F401
    Tracer,
    get_current_correlation_id,
    setup_tracing,
)
