# ryuu-observability-core

In-process observability primitives — zero external SDK dependencies.

| Primitive | Purpose |
|-----------|---------|
| `CostTracker` | Track LLM token spend per scope, enforce per-scope budgets |
| `AuditLogger` | JSONL append-only log with hash chain — tamper-evident |
| `RateLimiter` | Per-scope request rate limit (token bucket) |

For distributed tracing (OpenTelemetry spans → Jaeger/Tempo), install `ryuu-observability-otel`.
