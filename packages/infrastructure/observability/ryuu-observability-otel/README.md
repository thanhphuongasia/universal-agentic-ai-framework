# ryuu-observability-otel

OpenTelemetry tracer adapter for the Ryuu framework.

```python
from ryuu_observability_otel import Tracer, setup_tracing

setup_tracing(service_name="my-app", otlp_endpoint="http://jaeger:4317")
tracer = Tracer()

with tracer.span("agent.run"):
    ...  # spans exported via OTLP to Jaeger / Tempo / Datadog / …
```

Implements distributed tracing primitives separately from `ryuu-observability-core` (which has in-process cost/audit/rate-limit and no SDK deps).
