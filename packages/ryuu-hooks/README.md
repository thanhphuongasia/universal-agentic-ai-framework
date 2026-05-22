# ryuu-hooks

Hook system for dynamic agent lifecycle injection. Pattern inspired by Claude Agent SDK.

Lets product code inject behavior at lifecycle points without subclassing `BaseAgent`. Use cases:
- PII scrub before LLM calls
- Approval workflow for risky tool calls
- Custom metric emission
- Request modification

## Events (Phase 9.2)

| Event | Fires |
|-------|-------|
| `PRE_EXECUTE` / `POST_EXECUTE` | Around the whole agent.run() |
| `PRE_LLM` / `POST_LLM` | Around each LLM completion call |
| `PRE_TOOL` / `POST_TOOL` | Around each tool invocation |
| `ON_ERROR` | When an exception escapes the path |
| `ON_COMPLETE` | After successful completion |
| `ON_BUDGET_EXCEEDED` | When `BudgetExceededError` raised |
| `ON_RATE_LIMITED` | When `RateLimitTimeout` raised |

## Usage

```python
from ryuu_hooks import HookEvent, HookRegistry

registry = HookRegistry()

@registry.on(HookEvent.PRE_LLM)
async def scrub_pii(ctx):
    ctx.request.messages = [scrub(m) for m in ctx.request.messages]

agent = Agent(model="gpt-4o-mini", hooks=registry, ...)
```
