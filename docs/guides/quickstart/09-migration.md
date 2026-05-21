# Migration Path

← [Quickstart Index](README.md) | [All guides](../)

> Từ prototype → production. Day 1 Factory → Day 7 + observability → Day 30 class-based khi logic phức tạp.

---

## 8. Migration Path

```
Day 1:  Agent() factory                  ← prototype
Day 7:  Agent() + budget_usd + audit     ← production hardening
Day 30: BaseAgent subclass (nếu cần)     ← chuyển khi logic phức tạp
```

Factory và class chia sẻ same underlying primitives (BaseAgent, providers, observability). Chuyển từ factory sang class không phải rewrite — chỉ cần inline cái factory.build() làm.

---

## 9. Factory Design Spec (Reference)

Để implement, factory cần:

```
@dataclass
class Agent:
    model: str | list[str]           # "gpt-4o" | "openai:gpt-4o" | fallback chain
    instructions: str = ""
    tools: list[Callable] = field(default_factory=list)
    api_key: str | None = None       # default: env var auto-detect
    strategy: str = "auto"           # "auto" | "direct" | "react" | "evaluator" | "parallel"
    max_iterations: int = 5

    # Cross-cutting (None = NullObject)
    budget_usd: float | None = None
    rate_limit_rps: float | None = None
    audit: bool = False
    trace: bool = False

    # Hooks
    hooks: dict[str, list[Callable]] = field(default_factory=dict)

    # Knowledge (optional)
    knowledge: IKnowledgeBackbone | None = None

    async def run(self, message: str, **scope) -> AgentResult: ...
    async def stream(self, message: str, **scope) -> AsyncIterator[Event]: ...
```

**Auto-magic:**
1. `model` parse → provider class (openai/anthropic prefix)
2. `tools` callables → JSON schema (via inspect + docstring)
3. `budget_usd` → `CostTracker(CostPolicy(max_usd_per_session=...))`
4. `audit=True` → `AuditLogger()` writing to default JSONL
5. `**scope` kwargs (`user_id`, `session_id`, `domain`) → auto `ContextScope`
6. Returns `LeanAgent` wrapping `BaseAgent` + tool loop

---

## 10. Next Steps
