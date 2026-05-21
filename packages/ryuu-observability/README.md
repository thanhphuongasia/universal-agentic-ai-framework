# ryuu-core

Zero-dependency foundation for the [RYUU](https://github.com/core-corp/ryuu-framework) ecosystem.

No external dependencies — stdlib only.

## Install

```bash
pip install ryuu-core
```

## What's included

| Module | Contents |
|---|---|
| `ryuu_core.errors` | `RetryableError`, `DegradedError`, `FatalError`, `BudgetExceededError`, `retry_policy`, ... |
| `ryuu_core.context` | `ExecutionContext`, `ContextScope` |
| `ryuu_core.models` | `Cost`, `Task`, `AgentResult`, `StructuredIntent`, `CognitiveResult`, `CostEstimate`, ... |
| `ryuu_core.protocols` | `ICostTracker`, `ITracer`, `IAuditLogger`, `IRateLimiter` |
| `ryuu_core.nulls` | `NullCostTracker`, `NullTracer`, `NullAuditLogger`, `NullRateLimiter` |

## Why NullObjects matter

```python
# Before (required mocking 4 deps in every test):
agent = MyAgent(agent_id="test", cost_tracker=mock_tracker, tracer=mock_tracer, ...)

# After (NullObjects are the default):
agent = MyAgent(agent_id="test")
```

## Part of RYUU

Install `ryuu` for the full AI framework. `ryuu-core` is automatically pulled as a dependency.
