# Phase 10 — Factory `Agent()` Implementation Plan

> **Date**: 2026-05-21
> **Depends on**: Phase 8.8 Audit (must verify async non-blocking first)
> **Strategy**: Option A — DX-first. MVP Tuần 2, v2 Tuần 5.
> **See also**:
> - `docs/guides/quickstart.md` §1 (proposed API), §5.16 (4-mode breakdown)
> - `docs/architecture/uaaf-v2-architecture.md` §7.7 (Factory tier rationale)
> - `tasks/roadmap-phase8.8-to-14.md` (full roadmap context)

---

## 1. Goal

Single-line agent creation cho 90% chatbot + tool-calling use case:

```python
from ryuu import Agent

agent = Agent(model="gpt-4o-mini", instructions="You are a helper")
result = await agent.run("What is Python?")
```

Hoặc với tool + budget:

```python
def get_weather(city: str) -> dict:
    """Get current weather."""
    return {"city": city, "temp_c": 22}

agent = Agent(
    model="gpt-4o",
    instructions="You are an assistant",
    tools=[get_weather],
    budget_usd=1.0,
    audit=True,
)
result = await agent.run("Tokyo weather?", user_id="u-1", session_id="s-1")
```

**Class-based vẫn cover 10% advanced** (custom domain logic, multi-step). Factory KHÔNG thay thế class-based.

---

## 2. Scope MVP (Tuần 2)

### IN SCOPE

| Feature | Mức |
|---|---|
| Constructor: `Agent(model, instructions, tools, **limits, **cross_cutting)` | ✅ |
| **Prompt Mode 1**: `instructions=str` (shorthand cho system) | ✅ |
| **Tool Mode A**: inline callable list, schema auto từ docstring + type hints | ✅ |
| Provider auto-detect: `"gpt-4o"` → OpenAI, `"openai:gpt-4o"` explicit, `"anthropic:claude-sonnet-4"` | ✅ |
| **Per-call limits**: `max_tokens: int = None`, `temperature: float = 0.7` | ✅ |
| **Per-run limit**: `max_iterations: int = 5` (ReAct rounds) | ✅ |
| **Per-session budget**: `budget_usd: float \| None` (CostTracker enforce) | ✅ |
| Cross-cutting bật/tắt qua kwarg: `rate_limit_rps`, `audit: bool`, `trace: bool`, `verbose: bool` | ✅ |
| `verbose=True` — in ReAct steps ra stdout (CrewAI-style debug) | ✅ |
| `.run(message, **scope) -> AgentResult` | ✅ |
| Scope kwargs auto → `ContextScope`: `user_id`, `session_id`, `domain` | ✅ |
| ReAct tool loop internal (reuse `LLMAgent._react_loop` với `max_iterations`) | ✅ |
| Async ground truth (8.8 verified non-blocking) | ✅ |

### OUT OF SCOPE (defer to Phase 10.x v2 hoặc later)

| Feature | Defer to |
|---|---|
| Prompt Mode 2: `system=str`, `user_template=str`, `examples=[]` | 10.x |
| Prompt Mode 3: `system=Path("file.md")` | 10.x |
| Prompt Mode 4: `prompt="project:version:name"` YAML reference | 10.x |
| Tool Mode C/D: pre-built `tool_registry=` | 10.x |
| `hooks=` param | 10.x (sau Phase 9) |
| `verifiers=[...]` | 10.x (sau Phase 2 guardrail) |
| `strategy=` hint | 10.x |
| `knowledge=` backbone | 11 (sau RAG) |
| **`.stream()` AsyncIterator** với event types (token/thought/tool_call/...) | 10.x |
| **`budget_tokens=`** alt to budget_usd | 10.x (USD primary) |
| Multi-provider fallback chain `model=[...]` | 10.x |
| Multi-agent facades (`Chain`, `FanOut`, ...) | 10.5 |

---

## 3. File Structure

> **Decision (rev 1, 2026-05-21)**: Use **Option A** — add Agent vào root `ryuu/`, KHÔNG tạo `packages/ryuu/`. Lý do: root `ryuu/` đã là top-level facade trong root `pyproject.toml`. Tạo `packages/ryuu/` sẽ conflict namespace.

```
ryuu/                                       # ← existing top-level facade (root)
├── __init__.py                             # MODIFY: re-export Agent
├── factory.py                              # NEW: Agent dataclass + build logic
├── _provider_detect.py                     # NEW: parse "openai:gpt-4o" → provider
├── _tool_introspect.py                     # NEW: callable → ITool auto schema
└── _scope_builder.py                       # NEW: **scope kwargs → ContextScope
└── ... (existing folders unchanged)

tests/unit/ryuu/                            # NEW: tests for factory
├── __init__.py
├── test_factory_basic.py                   # Mode 1 + cross-cutting null defaults (4)
├── test_factory_provider_detect.py         # model string parsing (6)
├── test_factory_tools.py                   # tool schema introspection (6)
├── test_factory_cross_cutting.py           # budget/audit/trace/rate/verbose toggle (10)
├── test_factory_limits.py                  # max_tokens/temperature/max_iterations (4)
└── test_factory_run.py                     # end-to-end với FakeLLMProvider (5)

tests/integration/ryuu/
└── test_factory_openai.py                  # SKIP if no OPENAI_API_KEY (2)
```

**Root `pyproject.toml`**: KHÔNG đổi — đã list tất cả `ryuu-*` packages làm dependency. Factory code chỉ import từ những package đã có.

---

## 4. API Spec (MVP)

```python
# packages/ryuu/src/ryuu/factory.py
from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Any

from ryuu_core.models import AgentResult
from ryuu_execution.llm_agent import LLMAgent
from ryuu_execution.tool_registry import ToolRegistry
from ryuu_providers.llm import ILLMProvider

@dataclass
class Agent:
    """Lean factory for single-agent + tool-calling use cases.

    Class-based BaseAgent vẫn dùng được cho advanced — Factory KHÔNG thay thế.
    """

    # Required
    model: str                                       # "gpt-4o" | "openai:gpt-4o" | "anthropic:claude-sonnet-4"

    # Prompt — Mode 1 only in MVP
    instructions: str = ""                           # shorthand cho system prompt

    # Tools — Mode A only in MVP
    tools: list[Callable[..., Any]] = field(default_factory=list)

    # ── Per-call LLM limits (sent với CompletionRequest) ──
    max_tokens: int | None = None                    # max output tokens per LLM call (None = provider default)
    temperature: float = 0.7

    # ── Per-run ReAct loop limit ──
    max_iterations: int = 5                          # max tool call rounds trong 1 .run()

    # ── Per-session cost cap (None = NullObject) ──
    budget_usd: float | None = None

    # ── Cross-cutting (None/False = NullObject) ──
    rate_limit_rps: float | None = None
    audit: bool = False         # JSONL hash chain (compliance)
    trace: bool = False         # OTel spans (observability)
    verbose: bool = False       # stdout ReAct steps (debug, CrewAI-style)

    # Provider override (optional — default: env var auto-detect)
    api_key: str | None = None

    # Internal — built lazily
    _agent: LLMAgent | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        """Build provider + tool registry + cross-cutting + LLMAgent."""
        provider = self._build_provider()
        tool_registry = self._build_tool_registry()
        cost_tracker, rate_limiter, audit_logger, tracer = self._build_cross_cutting()

        self._agent = _FactoryLLMAgent(
            agent_id=f"factory-{id(self)}",
            llm=provider,
            tool_registry=tool_registry,
            system_prompt=self.instructions,
            cost_tracker=cost_tracker,
            rate_limiter=rate_limiter,
            audit_logger=audit_logger,
            tracer=tracer,
        )

    async def run(self, message: str, **scope_kwargs: Any) -> AgentResult:
        """Execute agent with message + optional scope kwargs.

        Scope kwargs: user_id, session_id, domain.
        Returns AgentResult with output, cost, tool_calls, etc.
        """
        from ryuu_workflow.context import ContextScope, ExecutionContext
        from ryuu_core.models import Task
        import uuid

        scope = ContextScope(
            user_id=scope_kwargs.get("user_id", "anonymous"),
            session_id=scope_kwargs.get("session_id", str(uuid.uuid4())),
            domain=scope_kwargs.get("domain", "default"),
        )
        ctx = ExecutionContext(scope=scope, correlation_id=str(uuid.uuid4()))
        task = Task(task_id=str(uuid.uuid4()), payload={"query": message})
        return await self._agent.execute(task, ctx)

    # ── Private builders ─────────────────────────────────────────

    def _build_provider(self) -> ILLMProvider: ...
    def _build_tool_registry(self) -> ToolRegistry: ...
    def _build_cross_cutting(self) -> tuple: ...
```

### Validation

```python
def __post_init__(self) -> None:
    if not self.model:
        raise ValueError("model is required")
    if self.budget_usd is not None and self.budget_usd <= 0:
        raise ValueError("budget_usd must be positive")
    if self.rate_limit_rps is not None and self.rate_limit_rps <= 0:
        raise ValueError("rate_limit_rps must be positive")
    # ... rest of build
```

---

## 5. Provider Auto-Detect

```python
# _provider_detect.py
def build_provider(model: str, api_key: str | None = None) -> ILLMProvider:
    """Parse model string → ILLMProvider instance.

    Formats:
        "gpt-4o"                          → OpenAIProvider (default)
        "openai:gpt-4o"                   → OpenAIProvider (explicit)
        "anthropic:claude-sonnet-4"       → AnthropicProvider
        "anthropic:claude-haiku-4-5"      → AnthropicProvider
    """
    if ":" in model:
        provider_name, _model = model.split(":", 1)
    elif model.startswith(("gpt-", "o1-", "o3-")):
        provider_name = "openai"
    elif model.startswith("claude-"):
        provider_name = "anthropic"
    else:
        raise ValueError(f"Cannot auto-detect provider for model: {model}. "
                         f"Use explicit prefix: 'openai:{model}' or 'anthropic:{model}'.")

    if provider_name == "openai":
        from ryuu_providers.adapters.openai import OpenAIProvider
        return OpenAIProvider(api_key=api_key or os.getenv("OPENAI_API_KEY"))
    elif provider_name == "anthropic":
        from ryuu_providers.adapters.anthropic import AnthropicProvider
        return AnthropicProvider(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))
    else:
        raise ValueError(f"Unknown provider: {provider_name}")
```

---

## 6. Tool Schema Auto-Introspection

```python
# _tool_introspect.py
import inspect
from collections.abc import Callable
from typing import Any, get_type_hints

def build_tool_schema(fn: Callable) -> dict[str, Any]:
    """Generate OpenAI function-calling schema from callable.

    Extracts:
      - name: fn.__name__
      - description: first line of docstring
      - parameters: from type hints (str → string, int → integer, list → array, dict → object)
      - required: params without defaults
    """
    sig = inspect.signature(fn)
    hints = get_type_hints(fn)

    properties: dict[str, dict] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue
        hint = hints.get(name, str)
        properties[name] = _type_to_json_schema(hint)
        if param.default is inspect.Parameter.empty:
            required.append(name)

    return {
        "type": "function",
        "function": {
            "name": fn.__name__,
            "description": (fn.__doc__ or "").strip().split("\n")[0],
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }

_PY_TO_JSON = {
    str: {"type": "string"},
    int: {"type": "integer"},
    float: {"type": "number"},
    bool: {"type": "boolean"},
    list: {"type": "array"},
    dict: {"type": "object"},
}
```

**Edge cases để cover trong test:**
- `Optional[str]` → `{"type": "string", "nullable": true}`
- `list[str]` → `{"type": "array", "items": {"type": "string"}}`
- Default values → KHÔNG required
- Docstring nhiều dòng → chỉ lấy line 1 cho description
- Không có docstring → description = "" (warn log)

---

## 7. Cross-Cutting Wiring

```python
def _build_cross_cutting(self) -> tuple:
    """Build 4 cross-cutting concerns. None = NullObject."""
    from ryuu_core.nulls import (NullCostTracker, NullRateLimiter,
                                  NullAuditLogger, NullTracer)

    cost = NullCostTracker()
    if self.budget_usd is not None:
        from ryuu_observability.cost import RealCostTracker, CostPolicy
        cost = RealCostTracker(CostPolicy(max_usd_per_session=self.budget_usd))

    rate = NullRateLimiter()
    if self.rate_limit_rps is not None:
        from ryuu_observability.rate_limit import TokenBucketRateLimiter
        rate = TokenBucketRateLimiter(rps=self.rate_limit_rps)

    audit = NullAuditLogger()
    if self.audit:
        from ryuu_observability.audit import FileAuditLogger
        from pathlib import Path
        audit = FileAuditLogger(path=Path("./ryuu_audit.jsonl"))

    tracer = NullTracer()
    if self.trace:
        from ryuu_observability.tracer import OTelTracer
        tracer = OTelTracer()

    return cost, rate, audit, tracer
```

---

## 8. Test Strategy (TDD)

### 8.1 RED first — list test cases

| Test file | Cases | Cover |
|---|---|---|
| `test_factory_basic.py` | 4 | Smoke + null defaults + validation errors |
| `test_factory_tools.py` | 6 | Schema từ str/int/float/bool/list/dict; required vs optional; docstring |
| `test_factory_cross_cutting.py` | 8 | Each of 4 toggles: off (Null) vs on (Real) — 2 cases × 4 |
| `test_factory_provider_detect.py` | 6 | Auto-detect gpt-/claude-/o1-; explicit prefix; unknown raises |
| `test_factory_run.py` | 5 | FakeLLMProvider — single call, tool call, error, scope wiring |
| `test_factory_openai.py` | 2 | Integration: 1 call, 1 tool call (SKIP if no key) |

**Total: 31 unit tests + 2 integration.**

### 8.2 Example test

```python
# tests/unit/ryuu/test_factory_basic.py
import pytest
from ryuu import Agent

def test_smoke_minimal_args():
    agent = Agent(model="gpt-4o-mini")
    assert agent.model == "gpt-4o-mini"

def test_null_cross_cutting_defaults():
    agent = Agent(model="gpt-4o-mini")
    from ryuu_core.nulls import NullCostTracker
    assert isinstance(agent._agent.cost_tracker, NullCostTracker)

def test_budget_negative_raises():
    with pytest.raises(ValueError, match="must be positive"):
        Agent(model="gpt-4o-mini", budget_usd=-1.0)

def test_unknown_provider_raises():
    with pytest.raises(ValueError, match="Cannot auto-detect"):
        Agent(model="unknown-model-xyz")
```

### 8.3 Coverage target

- Line coverage ≥ 90% cho `packages/ryuu/`
- Branch coverage ≥ 85%
- Integration test passes với real OpenAI (manual run)

---

## 9. Migration / Docs

### 9.1 Quickstart update

- §1.1-1.5 ở quickstart đã có proposed API → mark ✅ ready after Phase 10 MVP
- §5.16 update: remove "🔲 Phase 10" status, show concrete examples chạy được

### 9.2 README

Update root `README.md`:
- Quick start example dùng `Agent()` factory (thay class-based hiện tại)
- Bảng package: thêm `ryuu` (top-level facade)

### 9.3 Example mới

Tạo `examples/factory_quickstart/`:
- `chatbot.py` — Mode 1 inline (~20 dòng)
- `tool_calling.py` — tools= callable list (~30 dòng)
- `production.py` — bật full cross-cutting (~40 dòng)

So sánh với `examples/todo_app/agent.py` (149 dòng class-based) để show lean.

---

## 10. Release

- Tag: `v0.3.0a1` (alpha — Factory MVP, không có hooks/multi-agent)
- CHANGELOG entry: "Phase 10 — Factory MVP. Single-agent inline mode."
- `pip install ryuu` lần đầu hoạt động end-to-end

---

## 11. Risk & Mitigation

| Risk | Mitigation |
|---|---|
| Provider auto-detect sai model mới (vd `gpt-5`) | Explicit prefix `openai:gpt-5` luôn override; doc warning |
| Tool schema sai cho type phức tạp (`Union`, `TypedDict`) | Phase 10 MVP chỉ cover primitive + list/dict. Phase 10.x extend |
| Cross-cutting kwargs dễ nhầm (`audit=True` vs `audit_path=...`) | Phase 10 chỉ bool toggle, default path. Phase 10.x add path override |
| Factory hide quá nhiều magic → debug khó | Log INFO khi build provider/tool/cross-cutting. Expose `agent._agent` để introspect |
| User expect `hooks=` từ ngày 1 | Doc rõ "Hook param: Phase 10.x". Class-based override `_execute` workaround |

---

## 12. Streaming Design (Defer to Phase 10.x)

Streaming **không có trong MVP** vì cần design event types kỹ. Khi implement Phase 10.x:

```python
async for event in agent.stream("Explain quantum"):
    match event.type:
        case "token":        print(event.text, end="")
        case "thought":      print(f"\n💭 {event.text}")
        case "tool_call":    print(f"\n🔧 {event.tool_name}({event.args})")
        case "tool_result":  print(f"\n📤 {event.result}")
        case "final":        print(f"\n✅ done. cost=${event.cost.usd:.4f}")
```

**Event types đề xuất:**

| Event | When fires | Fields |
|---|---|---|
| `token` | Token-by-token LLM stream | `text: str` |
| `thought` | ReAct reasoning between tool calls | `text: str` |
| `tool_call` | Trước khi execute tool | `tool_name: str, args: dict` |
| `tool_result` | Sau khi tool trả result | `tool_name: str, result: Any` |
| `error` | Exception trong loop | `error: Exception` |
| `final` | Done, có final answer | `output: str, cost: Cost` |

**Implementation note**: Reuse existing `StreamManager` từ `ryuu-runtime` (đã có SSE/QueueCallbacks). Factory `.stream()` chỉ là wrapper bridge LLM stream events + tool events → `Event` dataclass.

---

## 13. Limits Disambiguation

Để tránh nhầm khi user đọc API:

| Param | Đơn vị | Scope | Khi fail thì gì xảy ra |
|---|---|---|---|
| `max_tokens` | tokens | 1 LLM call output | LLM truncate, finish_reason="length" |
| `temperature` | float 0-2 | 1 LLM call | (không fail — control randomness) |
| `max_iterations` | rounds | 1 `.run()` ReAct loop | `MaxIterationsExceededError` raise |
| `budget_usd` | USD | session (per ContextScope) | `BudgetExceededError` raise |
| `rate_limit_rps` | req/sec | scope (per user/session) | `RateLimitTimeout` raise hoặc backpressure |

**Worst case token estimate:** `max_tokens × max_iterations × 2` (input + output mỗi vòng). Vd: `max_tokens=1024, max_iterations=5` → ≤ 10,240 tokens per `.run()`.

**Khi user hỏi "giới hạn ở đâu?":**
- "Tôi muốn LLM output ngắn" → `max_tokens`
- "Tôi muốn ReAct không loop mãi" → `max_iterations`
- "Tôi muốn không tốn quá $1/session" → `budget_usd`
- "Tôi muốn rate limit per user" → `rate_limit_rps` + scope kwargs

---

## 14. Definition of Done

- [ ] `packages/ryuu/` scaffolded, `pyproject.toml` valid
- [ ] 31 unit tests GREEN + 2 integration skipped (no key) or pass (with key)
- [ ] Coverage ≥ 90% line, ≥ 85% branch
- [ ] `examples/factory_quickstart/{chatbot,tool_calling,production}.py` chạy thật với `OPENAI_API_KEY`
- [ ] Quickstart §1 + §5.16 unmark 🔲 → ✅ cho Mode 1 + Mode A
- [ ] README root example dùng `Agent()` factory
- [ ] CHANGELOG entry
- [ ] Tag `v0.3.0a1` ready (chưa publish)
