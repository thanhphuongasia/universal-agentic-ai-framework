# Hooks — Dynamic Lifecycle Injection

> **Goal**: Cho phép product inject logic vào agent lifecycle mà không cần subclass `BaseAgent`. Học từ **Claude Agent SDK** hooks pattern.

---

## 1. Tại sao cần hooks?

Cross-cutting concerns mà framework không cover hết:
- **PII filtering** — scrub email/SSN trước khi gửi LLM hoặc log
- **Compliance gating** — block tool calls vượt threshold (refund > $1000)
- **Custom metrics** — đếm tool usage, latency per tool
- **A/B testing** — log decisions để analyze sau
- **Caching** — short-circuit LLM calls nếu cache hit
- **Approval workflow** — pause + chờ human approve trước action sensitive

Không hook → subclass `BaseAgent` cho mỗi variant. Hooks → 1 agent class, nhiều hook combination.

---

## 2. Claude SDK Style (Reference)

Claude Agent SDK pattern:

```
agent = Agent(
    model="claude-sonnet-4",
    tools=[process_refund, lookup_customer],
    hooks={
        "PreToolUse":  [pii_filter, audit_logger],
        "PostToolUse": [refund_limit, metrics_recorder],
        "UserPromptSubmit": [moderation_check],
        "Stop": [save_session],
    },
)
```

Hook signature: `async def hook(ctx: HookContext) -> HookContext | None`
- Return `None` → pass through unchanged
- Return modified `HookContext` → mutate downstream state
- `raise` → block execution (with specific exception type)

---

## 3. RYUU Hook Lifecycle

```
┌──────────────────────────────────────────────────────────────┐
│ REQUEST FLOW                                                 │
│                                                              │
│   user message                                               │
│      │                                                       │
│      ▼                                                       │
│   ┌─────────────────────────┐                                │
│   │ on_request              │  ← intercept raw user input    │
│   └─────────────────────────┘                                │
│      │                                                       │
│      ▼                                                       │
│   IntentAnalyzer → StrategySelector                          │
│      │                                                       │
│      ▼                                                       │
│   ┌─────────────────────────┐                                │
│   │ pre_execute             │  ← before agent._execute()     │
│   └─────────────────────────┘                                │
│      │                                                       │
│      ▼                                                       │
│   ┌─── ReAct/Direct loop ───┐                                │
│   │   ┌─────────────────┐   │                                │
│   │   │ pre_llm         │   │  ← before each LLM call        │
│   │   └─────────────────┘   │                                │
│   │   LLM.complete()        │                                │
│   │   ┌─────────────────┐   │                                │
│   │   │ post_llm        │   │  ← after LLM response          │
│   │   └─────────────────┘   │                                │
│   │   ┌─────────────────┐   │                                │
│   │   │ pre_tool        │   │  ← before each tool dispatch   │
│   │   └─────────────────┘   │                                │
│   │   Tool.execute()        │                                │
│   │   ┌─────────────────┐   │                                │
│   │   │ post_tool       │   │  ← after each tool result      │
│   │   └─────────────────┘   │                                │
│   └─────────────────────────┘                                │
│      │                                                       │
│      ▼                                                       │
│   ┌─────────────────────────┐                                │
│   │ post_execute            │  ← after agent._execute()      │
│   └─────────────────────────┘                                │
│      │                                                       │
│      ▼                                                       │
│   ┌─────────────────────────┐                                │
│   │ on_complete             │  ← final result ready          │
│   └─────────────────────────┘                                │
│                                                              │
│ ERROR PATHS (parallel)                                       │
│   on_error              ← any unhandled exception            │
│   on_budget_exceeded    ← CostTracker.enforce() raises       │
│   on_rate_limited       ← RateLimiter.acquire() timeout      │
└──────────────────────────────────────────────────────────────┘
```

---

## 4. Hook Event Types

```
class HookEvent(StrEnum):
    # Request lifecycle
    ON_REQUEST          = "on_request"           # raw input received
    PRE_EXECUTE         = "pre_execute"          # before _execute()
    POST_EXECUTE        = "post_execute"         # after _execute()
    ON_COMPLETE         = "on_complete"          # final result ready

    # Per-iteration (ReAct/Direct loop)
    PRE_LLM             = "pre_llm"              # before LLM.complete()
    POST_LLM            = "post_llm"             # after LLM response
    PRE_TOOL            = "pre_tool"             # before tool dispatch
    POST_TOOL           = "post_tool"            # after tool result

    # Error paths
    ON_ERROR            = "on_error"             # any exception
    ON_BUDGET_EXCEEDED  = "on_budget_exceeded"   # cost cap hit
    ON_RATE_LIMITED     = "on_rate_limited"      # rate limit timeout
```

---

## 5. HookContext — Typed Data Per Event

Different events carry different payload. Use union types:

```
@dataclass(frozen=True)
class HookContextBase:
    event: HookEvent
    task_id: str
    agent_id: str
    scope_key: str
    correlation_id: str
    timestamp: float

@dataclass(frozen=True)
class PreToolContext(HookContextBase):
    tool_name: str
    args: dict[str, Any]              # mutable via return value

@dataclass(frozen=True)
class PostToolContext(HookContextBase):
    tool_name: str
    args: dict[str, Any]
    result: Any                       # mutable via return value
    latency_ms: float

@dataclass(frozen=True)
class PreLLMContext(HookContextBase):
    request: CompletionRequest        # mutable
    iteration: int                    # 0, 1, 2... in ReAct loop

@dataclass(frozen=True)
class PostLLMContext(HookContextBase):
    request: CompletionRequest
    response: Response                # mutable
    iteration: int
    cost: Cost
```

---

## 6. Hook Function Signature

```
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T", bound=HookContextBase)

HookFn = Callable[[T], Awaitable[T | None]]

# Examples:
PreToolHook = Callable[[PreToolContext], Awaitable[PreToolContext | None]]
PostToolHook = Callable[[PostToolContext], Awaitable[PostToolContext | None]]
```

**Contract:**
- `return None` → no changes
- `return modified ctx` → downstream sees mutated state
- `raise HookBlockedError(reason)` → block + audit + raise to caller
- `raise PermissionError` → block + raise (specific exception)

---

## 7. Registration Styles

### Style A — Dict mapping (Claude SDK compatible)

```
agent = Agent(
    model="gpt-4o",
    tools=[process_refund],
    hooks={
        "pre_tool": [pii_filter],
        "post_tool": [refund_limit, metrics_recorder],
    },
)
```

### Style B — Decorator (Pydantic AI style)

```
agent = Agent(model="gpt-4o", tools=[process_refund])

@agent.hook("pre_tool")
async def pii_filter(ctx: PreToolContext) -> PreToolContext | None:
    cleaned_args = scrub_pii(ctx.args)
    return ctx.replace(args=cleaned_args)

@agent.hook("post_tool")
async def refund_limit(ctx: PostToolContext) -> None:
    if ctx.tool_name == "process_refund" and ctx.result["amount"] > 1000:
        raise PermissionError(f"Refund ${ctx.result['amount']} requires approval")
```

### Style C — HookRegistry instance (shared across agents)

```
registry = HookRegistry()
registry.register("pre_tool", pii_filter)
registry.register("post_tool", refund_limit)

agent_a = Agent(model="gpt-4o", hooks=registry)
agent_b = Agent(model="claude-sonnet-4", hooks=registry)
# Both agents share same hooks
```

### Style D — Class-based (typed, IDE-friendly)

```
class CustomerServiceHooks:
    async def pre_tool(self, ctx: PreToolContext) -> PreToolContext | None:
        return ctx.replace(args=scrub_pii(ctx.args))

    async def post_tool(self, ctx: PostToolContext) -> None:
        if ctx.tool_name == "process_refund" and ctx.result["amount"] > 1000:
            raise PermissionError("Refund cap exceeded")

agent = Agent(model="gpt-4o", hooks=CustomerServiceHooks())
```

---

## 8. Real Use Cases — Cookbook

### 8.1 PII Filter (PreToolUse style)

```
async def pii_filter(ctx: PreToolContext) -> PreToolContext | None:
    """Strip emails/SSN from tool args before dispatch."""
    scrubbed = {}
    for k, v in ctx.args.items():
        if isinstance(v, str):
            v = re.sub(r"\S+@\S+\.\S+", "[EMAIL]", v)
            v = re.sub(r"\d{3}-\d{2}-\d{4}", "[SSN]", v)
        scrubbed[k] = v
    return ctx.replace(args=scrubbed)
```

### 8.2 Refund Limit (PostToolUse + raise)

```
async def refund_limit(ctx: PostToolContext) -> None:
    if ctx.tool_name == "process_refund":
        amount = ctx.result.get("amount", 0)
        if amount > 1000:
            raise PermissionError(
                f"Refund ${amount} requires manager approval. "
                f"Correlation: {ctx.correlation_id}"
            )
```

### 8.3 Latency Metrics (PostTool — observe only)

```
import structlog
logger = structlog.get_logger()

async def tool_metrics(ctx: PostToolContext) -> None:
    await logger.ainfo(
        "tool_call",
        tool=ctx.tool_name,
        latency_ms=ctx.latency_ms,
        scope=ctx.scope_key,
    )
```

### 8.4 Response Cache (PreLLM short-circuit)

```
cache: dict[str, Response] = {}

async def cache_lookup(ctx: PreLLMContext) -> None:
    key = hash_request(ctx.request)
    if key in cache:
        # Short-circuit by raising special exception
        raise CacheHit(cache[key])

async def cache_store(ctx: PostLLMContext) -> None:
    key = hash_request(ctx.request)
    cache[key] = ctx.response
```

### 8.5 Human Approval (PreTool — pause + resume)

```
async def require_approval(ctx: PreToolContext) -> PreToolContext | None:
    if ctx.tool_name in {"delete_user", "process_refund"}:
        approval = await approval_queue.request(
            scope=ctx.scope_key,
            tool=ctx.tool_name,
            args=ctx.args,
            correlation_id=ctx.correlation_id,
        )
        if not approval.granted:
            raise PermissionError(f"Denied by {approval.reviewer}")
        return ctx.replace(args=approval.maybe_modified_args)
    return None
```

### 8.6 Cost Cap Per Tool

```
async def expensive_tool_cap(ctx: PreToolContext) -> None:
    if ctx.tool_name == "deep_research":
        usage = cost_tracker.get_usage(ctx.scope_key)
        if usage.total_usd > 0.50:
            raise PermissionError(f"deep_research disabled after $0.50 spent")
```

### 8.7 Compliance Audit (PostExecute)

```
async def gdpr_audit(ctx: PostExecuteContext) -> None:
    if "personal_data" in str(ctx.result.output).lower():
        await compliance_log.record(
            user_id=ctx.scope_key.split(":")[0],
            output_hash=hashlib.sha256(ctx.result.output.encode()).hexdigest(),
            correlation_id=ctx.correlation_id,
        )
```

---

## 9. HookRegistry Implementation

```
# packages/ryuu-core/src/ryuu_core/hooks.py

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

HookFn = Callable[[Any], Awaitable[Any | None]]


@dataclass
class HookRegistry:
    """Pluggable hook manager — fire async hooks at lifecycle events."""

    hooks: dict[HookEvent, list[HookFn]] = field(default_factory=lambda: defaultdict(list))

    def register(self, event: HookEvent, fn: HookFn) -> None:
        self.hooks[event].append(fn)

    def hook(self, event: HookEvent):
        """Decorator for registration."""
        def decorator(fn: HookFn) -> HookFn:
            self.register(event, fn)
            return fn
        return decorator

    async def fire(self, event: HookEvent, ctx: HookContextBase) -> HookContextBase:
        """Fire all hooks for an event sequentially. Pass mutated ctx through."""
        for fn in self.hooks.get(event, []):
            result = await fn(ctx)
            if result is not None:
                ctx = result
        return ctx

    async def fire_parallel(self, event: HookEvent, ctx: HookContextBase) -> None:
        """Fire all hooks concurrently — for fire-and-forget (metrics, logs)."""
        async with anyio.create_task_group() as tg:
            for fn in self.hooks.get(event, []):
                tg.start_soon(fn, ctx)
```

**Sequential vs Parallel:**
- `fire()` — for hooks that mutate context (PII filter, args rewriter)
- `fire_parallel()` — for fire-and-forget (logging, metrics) — không block lifecycle

---

## 10. Integration với BaseAgent

```
@dataclass
class BaseAgent(ABC):
    ...existing fields...
    hooks: HookRegistry = field(default_factory=HookRegistry)

    async def execute(self, task: Task, context: ExecutionContext) -> AgentResult:
        scope_key = context.scope.scope_key

        async with self.tracer.span(self.agent_id, task.task_id, context.correlation_id):
            await self.rate_limiter.acquire(scope_key, self.agent_id)

            # Fire PRE_EXECUTE
            pre_ctx = PreExecuteContext(
                event=HookEvent.PRE_EXECUTE,
                task_id=task.task_id, agent_id=self.agent_id,
                scope_key=scope_key, correlation_id=context.correlation_id,
                task=task,
            )
            pre_ctx = await self.hooks.fire(HookEvent.PRE_EXECUTE, pre_ctx)
            task = pre_ctx.task  # hooks may have mutated

            try:
                result = await self._execute(task, context)

                # Fire POST_EXECUTE (sequential — may transform result)
                post_ctx = await self.hooks.fire(HookEvent.POST_EXECUTE, ...)
                result = post_ctx.result

                self.cost_tracker.record(scope_key, result.cost)
                self.audit_logger.log_complete(...)
                return result

            except Exception as exc:
                await self.hooks.fire_parallel(HookEvent.ON_ERROR, ...)
                raise
```

---

## 11. Async-First Design

**Tất cả hooks là async** — không block event loop:

| Hook usage | Async required vì |
|---|---|
| PII filter (regex) | Pure CPU — could be sync, but async for consistency |
| Database lookup | I/O — async essential |
| Approval queue (wait for human) | Long pause — async essential |
| Metric write (Prometheus push) | Network I/O — async essential |
| File audit log | File I/O — async wraps via `anyio.to_thread` |

**Anti-pattern:**
```
async def bad_hook(ctx):
    time.sleep(5)              # 🔴 blocks event loop
    requests.get("http://...")  # 🔴 sync HTTP — blocks
```

**Correct:**
```
async def good_hook(ctx):
    await anyio.sleep(5)            # ✅
    async with httpx.AsyncClient() as c:
        await c.get("http://...")    # ✅
```

---

## 12. Performance — When to Worry

| # Hooks | Per request overhead | Concern? |
|---|---|---|
| 1-5 sync regex | < 1ms | No |
| 1-3 in-memory dict lookup | < 0.1ms | No |
| 1 async DB query | ~5-50ms | Maybe — use `fire_parallel` if observe-only |
| 1 HTTP webhook | ~100-500ms | Yes — use `fire_parallel` or queue |
| Human approval | seconds/minutes | Yes — use queue + resume pattern |

**Rule**: Mutating hooks → sequential (slow but correct). Observing hooks → parallel (fast, fire-and-forget).

---

## 13. Comparison với Claude SDK

| Feature | Claude SDK | RYUU (proposed) |
|---|---|---|
| Hook event types | 5 (PreToolUse, PostToolUse, UserPromptSubmit, Notification, Stop) | 10+ (full lifecycle) |
| Mutation | Via return value | Via return value |
| Block execution | `raise` | `raise` |
| Sequential vs parallel | Sequential only | Both (`fire` / `fire_parallel`) |
| Registration | Dict in constructor | Dict / Decorator / Class / Registry |
| Type safety | Partial | Full (typed HookContext per event) |
| Async | Sync only | Async-first |
| Multi-agent sharing | No | Yes (HookRegistry shareable) |

RYUU mở rộng Claude pattern thêm:
- Per-iteration hooks (pre_llm, post_llm) cho ReAct loop
- Error path hooks (on_budget_exceeded, on_rate_limited)
- Parallel fire mode cho observability hooks
- Typed contexts cho IDE support

---

## 14. Implementation Status

| Component | Status |
|---|---|
| `ReActCallbacks` (existing) | ✅ Shipped — narrow, for ReAct loop only |
| `HookRegistry` (new) | 🔴 Proposed |
| `HookEvent` enum (new) | 🔴 Proposed |
| `HookContext*` types (new) | 🔴 Proposed |
| BaseAgent integration | 🔴 Proposed |
| ToolRegistry integration | 🔴 Proposed |
| LLMAgent integration | 🔴 Proposed |
| Factory `hooks=` param | 🔴 Proposed (depends on factory) |

**Migration path:**
- Phase 1: Implement `HookRegistry` + 3 core events (pre/post tool, post execute)
- Phase 2: Wire into ToolRegistry + BaseAgent
- Phase 3: Add per-iteration hooks (pre/post llm) into LLMAgent
- Phase 4: Factory integration
- Existing `ReActCallbacks` giữ nguyên cho backwards compat — chỉ deprecate khi `HookEvent.PRE_LLM`/`POST_LLM` đủ stable

---

## 15. Open Questions

1. **Hook ordering** — Sequential trong order register? Hay có priority hint?
2. **Cross-event state** — Hook ở `pre_tool` set state, hook ở `post_tool` đọc — pass qua HookContext custom field?
3. **Error in hook** — Hook itself fail → fail entire request? Hay log + continue?
4. **Hook discovery** — Plugin system (entry points) cho 3rd party hooks?
5. **Hook composability** — Combine hooks (`AndHook(a, b)`, `OrHook(a, b)`) như middleware?

Open issues để discuss khi implement.

---

## Next Steps

1. Đọc [Quickstart](quickstart.md) — overview của Factory vs Class-based
2. Implement `HookRegistry` (Phase 1) khi factory work bắt đầu
3. Hook examples bổ sung vào `examples/todo_app/` để dogfood
