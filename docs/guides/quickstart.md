# RYUU Quickstart

> **Goal**: Agent đầu tiên chạy trong < 5 phút. Hiểu khi nào dùng **Factory** (90% use cases) vs **Class-based** (10% advanced).
>
> **Status legend**: ✅ available now | 🔲 planned (xem `tasks/roadmap-phase8.8-to-14.md`)

| Feature | Status | Phase |
|---|---|---|
| Class-based `BaseAgent` | ✅ | shipped |
| Async cross-cutting guarantee (≤10k QPS) | 🔲 | 8.8 |
| Hook system (10 events + parallel mode) | ✅ | 9 + 9.2 |
| Factory `Agent()` Mode 1 (inline) + Mode A (callable) | ✅ | 10 MVP |
| Factory Mode 2 (system + user_template + examples) | ✅ | 10.1 |
| Factory Mode 3 (file path) + Mode 4 (YAML ref) | ✅ | 10.2 |
| Factory Tool Modes B (ITool) + C (registry) + D (YAML schemas) | ✅ | 10.3 |
| Factory `.stream()` + `model=[list]` fallback + `budget_tokens=` | ✅ | 10.4 |
| Multi-agent facades (`Chain`, `FanOut`, `Router`, `Orchestrator`, `Evaluator`) | ✅ | 10.5 |
| `ryuu-knowledge-rag` (RAG) | 🔲 | 11 |
| `ryuu-batch` (batch API) | 🔲 | 12 |
| `ryuu-prompt-optimizer` | 🔲 | 13 |
| `ryuu-reasoning` (Z3/Prolog) | 🔲 | 14 |

---

## TL;DR — Khi nào dùng cái nào?

```
┌─────────────────────────────────────────────────────────┐
│ Chatbot / Tool-calling / RAG / Single domain?           │
│     → Agent()   [Factory — 1 line]                      │
│                                                         │
│ Multi-agent orchestration / Custom strategy routing /   │
│ Stateful workflow / Custom verifier pipeline?           │
│     → BaseAgent subclass  [Class-based]                 │
└─────────────────────────────────────────────────────────┘
```

**Mặc định**: dùng `Agent()` factory. Chỉ chuyển sang class-based khi factory không cover được.

---

## 1. Factory Style — Recommended (Proposed)

> ⚠️ Factory chưa implement. API design dưới đây tham khảo Pydantic AI + OpenAI Agents SDK + Claude SDK.

### 1.1 Simplest — Chatbot không có tool

```
from ryuu import Agent

agent = Agent(model="gpt-4o-mini")
result = await agent.run("What is Python?")
print(result.output)
```

3 dòng. Provider tự detect từ `OPENAI_API_KEY` env var. CostTracker/Tracer/Audit là NullObject.

### 1.2 Có tool calling

```
from ryuu import Agent

def lookup_customer(user_id: str) -> str:
    """Get customer profile by ID."""
    return f"Customer {user_id}: premium plan"

def check_order(order_id: str) -> str:
    """Check order shipping status."""
    return f"Order {order_id}: shipped 2 days ago"

agent = Agent(
    model="gpt-4o-mini",
    instructions="You are a customer service agent. Use tools to answer.",
    tools=[lookup_customer, check_order],
)

result = await agent.run("What's the status of order #123 for customer u-42?")
print(result.output)
```

Tool schema tự build từ docstring + type hints. Tool loop tự handle.

### 1.2.5 Mode 2 — Tách `system` + `user_template` + `examples` ✅

Khi cần few-shot examples hoặc user prompt có template variables:

```python
from ryuu import Agent


async def demo() -> None:
    agent = Agent(
        model="gpt-4o-mini",
        system="You are a translator. Output Vietnamese only.",
        user_template="Translate to VN: {text}",
        examples=[
            {"user": "Hello",  "assistant": "Xin chào"},
            {"user": "Thanks", "assistant": "Cảm ơn"},
        ],
    )

    # Template vars qua kwargs
    result = await agent.run(text="Good morning")
    # Reserved kwargs (user_id/session_id/domain) tự tách khỏi template vars
    result = await agent.run(text="Hello", user_id="u-42")
    print(result.output)
```

**Quy tắc:**
- Không thể mix `instructions` (Mode 1) và `system` (Mode 2) — chọn 1
- `examples` là list dict với key `user` + `assistant`; interleave thành user/assistant messages BEFORE real query
- Reserved scope kwargs: `user_id`, `session_id`, `domain`, `correlation_id`. Remaining kwargs → template vars

### 1.3 Production setup — Limits + Observability + Budget + Rate limit

```
from ryuu import Agent

agent = Agent(
    model="gpt-4o-mini",
    instructions="You are a customer service agent.",
    tools=[lookup_customer, check_order],

    # ── Per-call LLM limits ──
    max_tokens=1024,        # max output tokens MỖI LLM call
    temperature=0.3,        # default 0.7

    # ── Per-run ReAct limit ──
    max_iterations=5,       # max tool call rounds trong 1 .run() (default 5)

    # ── Per-session budget (USD primary, BudgetExceededError) ──
    budget_usd=1.00,

    # ── Cross-cutting toggles ──
    rate_limit_rps=10,      # token bucket per scope
    audit=True,             # JSONL hash chain (tamper-proof, compliance)
    trace=True,             # OpenTelemetry spans (observability)
    verbose=True,           # in ReAct steps ra stdout (debug, CrewAI-style)
)

# scope_key derived from kwargs (user_id, session_id, domain)
result = await agent.run(
    "Check order #123",
    user_id="customer-42",
    session_id="sess-001",
)
```

### 1.4 Multi-provider với fallback

```
agent = Agent(
    model=["anthropic:claude-sonnet-4", "openai:gpt-4o"],  # fallback chain
    tools=[...],
)
# Nếu Anthropic fail (rate limit, timeout) → tự retry với OpenAI
```

### 1.5 Strategy hint

```
# Default: "auto" — analyzer chọn strategy theo complexity
agent = Agent(model="gpt-4o", tools=[...])

# Force specific:
agent = Agent(model="gpt-4o", strategy="react", max_iterations=5)
agent = Agent(model="gpt-4o", strategy="evaluator", verify_with="gpt-4o")
agent = Agent(model="gpt-4o", strategy="parallel", fan_out_by="goal_id")
```

### 1.6 Hooks (Claude SDK style)

Hooks cho phép product inject logic vào agent lifecycle mà không cần subclass. Pattern học từ Claude Agent SDK.

```
from ryuu.hooks import HookEvent, PreToolContext, PostToolContext

async def pii_filter(ctx: PreToolContext) -> PreToolContext | None:
    """Scrub email/SSN trước khi tool call."""
    return ctx.replace(args=scrub_pii(ctx.args))

async def refund_limit(ctx: PostToolContext) -> None:
    """Block refund > $1000."""
    if ctx.tool_name == "process_refund" and ctx.result["amount"] > 1000:
        raise PermissionError(f"Refund ${ctx.result['amount']} requires approval")

agent = Agent(
    model="gpt-4o",
    tools=[process_refund],
    hooks={
        "pre_tool":  [pii_filter],
        "post_tool": [refund_limit],
    },
)
```

**10+ hook events** (pre_execute, post_execute, pre_llm, post_llm, pre_tool, post_tool, on_error, on_budget_exceeded, ...). Hooks có thể mutate context, block execution (raise), hoặc fire-and-forget parallel (metrics).

📖 **Xem chi tiết**: [Hooks Guide](hooks.md) — lifecycle diagram, all event types, registration styles (decorator/dict/class), 7 cookbook recipes, async-first design.

### 1.7 Streaming (🔲 Phase 10.x)

`.stream()` là **method khác**, không phải kwarg. Defer to Phase 10.x sau MVP.

```
async for event in agent.stream("Explain quantum entanglement"):
    match event.type:
        case "token":        print(event.text, end="", flush=True)   # token-by-token
        case "thought":      print(f"\n💭 {event.text}")             # ReAct reasoning
        case "tool_call":    print(f"\n🔧 {event.tool_name}({event.args})")
        case "tool_result":  print(f"\n📤 {event.result}")
        case "error":        print(f"\n❌ {event.error}")
        case "final":        print(f"\n✅ cost=${event.cost.usd:.4f}")
```

**6 event types:** `token` | `thought` | `tool_call` | `tool_result` | `error` | `final`.

### 1.8 Limits Disambiguation — 5 Param Khác Nhau

Dễ nhầm — xem nhanh:

| Param | Đơn vị | Scope | Khi fail |
|---|---|---|---|
| `max_tokens` | tokens | 1 LLM call output | LLM truncate (`finish_reason="length"`) |
| `temperature` | 0-2 | 1 LLM call | — (control randomness) |
| `max_iterations` | rounds | 1 `.run()` ReAct loop | `MaxIterationsExceededError` raise |
| `budget_usd` | USD | session (per scope) | `BudgetExceededError` raise |
| `rate_limit_rps` | req/sec | scope | `RateLimitTimeout` raise |

**Worst case token estimate per `.run()`:** `max_tokens × max_iterations × 2`. Vd `1024 × 5 × 2 = 10,240 tokens`.

**Hỏi nào dùng cái nào:**
- "Output ngắn lại" → `max_tokens`
- "ReAct không loop mãi" → `max_iterations`
- "Không tốn quá $1/session" → `budget_usd`
- "Rate limit per user" → `rate_limit_rps` + `user_id` scope kwarg

### 1.9 Output Channels — `verbose` vs `stream()` vs `audit` vs `trace`

4 cách output thông tin lifecycle, **không loại trừ nhau** — có thể bật tất:

| Channel | Output đi đâu | Format | Khi nào dùng |
|---|---|---|---|
| `verbose=True` | stdout console | Human-readable emoji | Dev/debug local (CrewAI-style) |
| `.stream()` | AsyncIterator → app code | `Event` dataclass | UI streaming, programmatic |
| `audit=True` | `./ryuu_audit.jsonl` | JSONL hash chain | Compliance, audit trail |
| `trace=True` | OTel exporter | OpenTelemetry spans | Observability dashboard |

```python
# Bật tất 4 — không conflict
async def demo() -> None:
    agent = Agent(
        model="gpt-4o",
        verbose=True,        # console nhìn được khi dev
        audit=True,          # JSONL ghi file
        trace=True,          # OTel cho Grafana/Jaeger
    )
    async for ev in agent.stream("..."):    # đồng thời stream tới UI
        update_ui(ev)
```

**Verbose output example:**

```
🤔 Thought: User asks about Tokyo weather, need to call get_weather
🔧 Action: get_weather(city="Tokyo")
📤 Observation: {"city": "Tokyo", "temp_c": 22}
✅ Final: It's 22°C in Tokyo today.
```

### 1.10 Reasoning Techniques — CoT, ToT, Self-Consistency, Reflection

Các kỹ thuật prompting/reasoning map sang RYUU primitives:

| Technique | RYUU equivalent | Status |
|---|---|---|
| **Chain-of-Thought (CoT)** | Prompt "step by step" HOẶC `strategy="react"` (built-in) | ✅ |
| **ReAct** (Reason + Act) | `strategy="react"` với tools (default cho Factory) | ✅ |
| **Self-Consistency** | `strategy="best_of_n", n=5, vote="majority"` | 🔲 Phase 10.x |
| **Tree-of-Thought (ToT)** | `FanOut` + `Evaluator` recursion HOẶC custom strategy | 🔲 Phase 10.5 |
| **Reflection / Self-Critique** | `strategy="evaluator", verifier="llm_judge", max_refines=2` | ✅ class / 🔲 facade |
| **Plan-and-Execute** | `Orchestrator` (main plans, workers execute) | 🔲 Phase 10.5 |
| **Multi-Agent Debate** | Custom `Chain` với critic agent | 🔲 Phase 10.5 |

#### CoT — Đơn giản nhất

```python
# Cách 1: Prompt-only
agent = Agent(
    model="gpt-4o",
    instructions="Think step by step. Show your reasoning before answering.",
)

# Cách 2: ReAct strategy (default cho Factory) — CoT built-in
agent = Agent(model="gpt-4o", tools=[search, calculator])
# Internal: Thought → Action → Observation → Thought → ... → Final
```

#### Self-Consistency — Sample N + vote

```
# 🔲 Phase 10.x
agent = Agent(
    model="gpt-4o",
    strategy="best_of_n",
    n=5,                       # 5 candidates parallel
    vote="majority",           # or "llm_judge", "verifier_score"
    temperature=0.9,           # high temp → diverse
)
result = await agent.run("What's 17 × 23?")
```

#### Tree-of-Thought — Branching + Evaluator

ToT cần nhiều LLM call + scoring → dùng multi-agent pattern (Phase 10.5):

```
from ryuu import Agent, FanOut, Evaluator

# Step 1: Generate N reasoning branches
branches = await FanOut(
    agent=Agent(model="gpt-4o", instructions="Suggest 1 possible reasoning step"),
    items=range(5), temperature=0.9,
).run("Problem: ...")

# Step 2: Evaluate, pick best
best = await Evaluator(
    generator=Agent(model="gpt-4o", instructions="Pick best branch"),
    verifier="llm_judge",
).run(branches)

# Step 3: Recurse expand best (loop)
```

Hoặc custom class-based `ICognitiveStrategy` cho full ToT (BFS/DFS through tree).

#### Reflection — Generate → Critique → Refine

```
# 🔲 Phase 10.x facade
agent = Agent(
    model="gpt-4o",
    strategy="evaluator",
    verifier="llm_judge",        # or "schema", "formal" (Z3)
    max_refines=2,                # max retry rounds
)
result = await agent.run("Write Python code for quicksort")
# Internal: generate → judge → if fail, refine prompt + retry
```

**Khi nào dùng cái nào:**
- Single LLM, cần reasoning rõ → **CoT** prompt
- Có tool/external call → **ReAct** (default)
- Câu hỏi math/logic, cần đúng → **Self-Consistency** vote
- Problem phức tạp, multi-step search → **ToT** (đắt nhất)
- Output có thể sai, cần auto-fix → **Reflection**
- Plan trước, execute sau (codebase analysis) → **Plan-and-Execute** (`Orchestrator`)

### 1.11 Prompt + Reasoning Technique — Có Cần Few-Shot Không?

#### TL;DR

**Modern LLM (gpt-4o, claude-sonnet-4) hiểu CoT/ReAct zero-shot** — không cần few-shot. Nhưng cho **specialized domain** (finance/medical/legal) hoặc **complex tool usage** (5+ step sequence), few-shot examples vẫn improve accuracy **+10-30%**.

**Quy tắc 1 dòng:** Start zero-shot → đo eval → add 2-5 example KHI eval < target.

#### RYUU Auto-Inject vs User Provide

| Technique | RYUU auto-inject | User cần làm | Few-shot cần? |
|---|---|---|---|
| **Prompt CoT** | — | `instructions="Think step by step"` | Hiếm khi |
| **ReAct (no tools)** | Hint reasoning | `instructions=...` | Hiếm khi |
| **ReAct (with tools)** | Tool schemas + tool-calling hint | `instructions` + `tools=[...]` | Có nếu tool phức tạp |
| **Self-Consistency** | Sample N times (no inject) | Cùng prompt như single | Không |
| **Tree-of-Thought** | Branch + eval templates | Domain instructions | **Có** — guide branch quality |
| **Reflection** | Critique + refine templates | Domain instructions + verifier | Có nếu critique style đặc thù |
| **Plan-and-Execute** | Plan format spec | Worker instructions | Có cho complex domain |

#### Khi NÊN Add Few-Shot Examples

- Domain-specific reasoning (finance, medical, legal)
- Output format phức tạp (nested JSON schema)
- Tool usage non-obvious (sequence 3-5 API call)
- ToT branch generation (guide diversity)
- Critique style cho Reflection (show "good critique" vs "bad")

#### Khi KHÔNG Cần Few-Shot

- Đếm/math cơ bản, translation, summarization
- Tool calling đơn giản (1-2 tools rõ ràng)
- Free-form Q&A
- Modern model + standard task

#### Cách Inject Examples

```python
# Inline qua Factory (Phase 10.x)
agent = Agent(
    model="gpt-4o",
    instructions="You are a financial analyst.",
    tools=[get_price, analyze_chart],
    examples=[
        {
            "user": "Should I buy AAPL?",
            "assistant": (
                "Step by step:\n"
                "1. get_price('AAPL') → check current\n"
                "2. analyze_chart('AAPL', '1mo') → trend\n"
                "3. Compare P/E to sector\n"
                "Recommendation: HOLD"
            ),
        },
    ],
)
```

Hoặc qua YAML (Mode 4):

```yaml
prompts:
  analyze_stock:
    system: "You are a financial analyst."
    examples:
      - user: "Should I buy AAPL?"
        assistant: "1. Check price... 2. Analyze trend..."
    user: "{query}"
```

#### Strategy-Specific Templates (🔲 Phase 10.x ToT/Reflection)

ToT/Reflection có template riêng, override qua kwarg:

```python
# ToT — override branch generation
agent = Agent(
    model="gpt-4o",
    strategy="tot",
    tot_branch_template=(
        "Given: {problem}\nCurrent path: {path}\n"
        "Suggest 1 NEXT step. Be specific."
    ),
    tot_eval_template="Rate 1-10:\n{step}\nScore:",
)

# Reflection — override critique
agent = Agent(
    model="gpt-4o",
    strategy="evaluator",
    critique_template=(
        "Critique for: correctness, completeness, clarity.\n"
        "Output: {output}\n"
        "Return JSON {{passed: bool, feedback: str}}"
    ),
)
```

#### Khi Examples KHÔNG Giúp (Có Hại)

- **> 5 examples** → overfit, cost tăng 30-50%, distract from real query
- **Examples không match domain** → confuse LLM
- **Examples sai/inconsistent** → LLM học pattern sai
- **Modern model + simple task** → noise, không tăng accuracy

**Quy tắc:** Start zero-shot. Đo accuracy qua eval suite. Add 2-5 examples KHI eval < target, không phải mặc định.

#### RYUU Built-In Prompts — Internal Reference

Để minh bạch, RYUU inject template gì cho từng strategy (Phase 10.x):

```python
# packages/ryuu/src/ryuu/_strategy_prompts.py
_STRATEGY_PROMPTS = {
    "react": {
        "system_suffix": "\n\nIf you need information, use the available tools.",
        # Không cần Thought/Action/Observation text — function-calling API handle
    },
    "best_of_n": {
        # No prompt change — chỉ sample N lần ở high temperature
    },
    "tot": {
        "branch_template": (
            "Given context: {ctx}\n"
            "Current reasoning path: {path}\n"
            "Suggest 1 NEXT reasoning step. Be specific, no hedging."
        ),
        "eval_template": (
            "Rate this reasoning step 1-10:\n{step}\n"
            "Reason briefly, then output 'Score: X'"
        ),
    },
    "evaluator": {
        "critique_template": (
            "Critique the output for: correctness, completeness, clarity.\n"
            "Output: {output}\n"
            "Return JSON: {{'passed': bool, 'feedback': str}}"
        ),
        "refine_template": (
            "Previous attempt had this issue:\n{feedback}\n"
            "Retry with the issue addressed."
        ),
    },
    "plan_execute": {
        "plan_template": (
            "Break this task into 2-5 ordered steps.\n"
            "Task: {task}\n"
            "Return JSON list of step descriptions."
        ),
    },
}
```

**Override qua kwarg trong Factory:**

```python
agent = Agent(
    model="gpt-4o",
    strategy="tot",
    tot_branch_template="...",      # override default branch template
    tot_eval_template="...",         # override default eval template
)

agent = Agent(
    model="gpt-4o",
    strategy="evaluator",
    critique_template="...",         # override default critique
    refine_template="...",           # override default refine
)
```

**Minh bạch hoá**: User luôn biết RYUU inject gì → tránh "magic" làm khó debug khi LLM behavior unexpected.

---

## 2. Class-Based — Advanced & Flexible

Cần khi factory không cover:
- Custom domain logic với multiple LLM calls trong 1 task
- Stateful agent với memory backbone custom
- Multi-agent orchestration (AgentPool + custom routing)
- Custom verifier pipeline trong evaluator strategy
- Override execution flow (caching, fallback chains, A/B test prompts)

### 2.1 Skeleton

```python
import anyio
from dataclasses import dataclass, field
from ryuu_execution.agent import BaseAgent, Task, AgentResult
from ryuu_core.models import Cost
from ryuu_providers.adapters.openai import OpenAIProvider
from ryuu_providers.llm import CompletionRequest, Message
from ryuu_observability.cost import CostTracker, CostPolicy
from ryuu_workflow.context import ContextScope, ExecutionContext


@dataclass
class CustomerServiceAgent(BaseAgent):
    llm: OpenAIProvider = field(default_factory=lambda: OpenAIProvider(api_key="sk-..."))

    async def _execute(self, task: Task, context: ExecutionContext) -> AgentResult:
        # Multi-step logic: classify intent → fetch data → generate reply
        intent = await self._classify(task.payload.get("message", ""))
        data = await self._fetch_context(intent, context)
        reply = await self._generate_reply(intent, data)

        return AgentResult(
            task_id=task.task_id,
            output=reply.content,
            cost=Cost(
                input_tokens=reply.usage.input_tokens,
                output_tokens=reply.usage.output_tokens,
                usd=0.001,
                provider="openai",
                model="gpt-4o-mini",
            ),
        )

    async def _classify(self, message: str):
        request = CompletionRequest(
            messages=[Message(role="user", content=message)],
            model="gpt-4o-mini",
        )
        return await self.llm.complete(request)

    async def _fetch_context(self, intent, ctx): ...
    async def _generate_reply(self, intent, data): ...


async def main():
    scope = ContextScope(user_id="customer-42", session_id="s1", domain="support")
    ctx = ExecutionContext(scope=scope, correlation_id="req-001")

    agent = CustomerServiceAgent(
        agent_id="support-agent",
        cost_tracker=CostTracker(CostPolicy(max_usd_per_session=1.0)),
    )

    result = await agent.execute(
        Task(task_id="t1", payload={"message": "Check my order status"}),
        ctx,
    )
    print(result.output)


anyio.run(main)
```

Cross-cutting (Tracer, AuditLogger, RateLimiter) optional — defaults là NullObject, framework không bắt buộc inject.

---

## 3. Cross-cutting Features — Bật/Tắt

Tất cả 3 mục dưới đây áp dụng cho **cả Factory và Class-based**. Factory dùng kwarg đơn giản, class-based inject constructor.

### 3.1 Observability — Default OFF, Opt-in

NullObject pattern: không khai báo = không log, không track, không trace, không rate-limit. Zero overhead.

**Factory (🔲 planned):**

```python
from ryuu import Agent

# Hoàn toàn OFF — chỉ chat, không observability
agent = Agent(model="gpt-4o-mini")

# Bật từng cái khi cần
agent = Agent(
    model="gpt-4o-mini",
    budget_usd=1.0,        # ON: CostTracker enforce $1/session
    rate_limit_rps=10,     # ON: TokenBucketRateLimiter
    audit=True,            # ON: AuditLogger ghi JSONL hash chain
    trace=True,            # ON: OTel Tracer spans
)
```

**Class-based (✅ available now):**

```python
from ryuu_execution.agent import BaseAgent
from ryuu_observability.cost import RealCostTracker, CostPolicy
from ryuu_observability.audit import FileAuditLogger
from ryuu_observability.tracer import OTelTracer
from ryuu_observability.rate_limit import TokenBucketRateLimiter

# Hoàn toàn OFF
agent = MyAgent(agent_id="lean")    # 4 NullObject defaults

# Bật từng cái
agent = MyAgent(
    agent_id="prod",
    cost_tracker=RealCostTracker(CostPolicy(max_usd_per_session=1.0)),
    audit_logger=FileAuditLogger(path="./audit.jsonl"),
    tracer=OTelTracer(),
    rate_limiter=TokenBucketRateLimiter(rps=10),
)
```

**Async guarantee (🔲 Phase 8.8):** Tất cả 4 cross-cutting đảm bảo non-blocking dưới 10k QPS. Verify qua stress test (xem architecture §7.6).

---

### 3.2 Hooks — Dynamic Lifecycle Injection (🔲 Phase 9)

Hook = inject Python callable vào event lifecycle mà không cần subclass. Lấy cảm hứng từ Claude Agent SDK.

**Lifecycle events:**

```
pre_execute → pre_llm → post_llm → pre_tool → post_tool → post_execute → on_complete
                                                                          (+ on_error,
                                                                           on_budget_exceeded,
                                                                           on_rate_limited)
```

**Ví dụ — PII scrub trước tool call (🔲 Phase 9):**

```
from ryuu import Agent
from ryuu.hooks import PreToolContext

async def pii_scrub(ctx: PreToolContext) -> PreToolContext:
    """Replace email/SSN trong args trước khi gửi tool."""
    return ctx.replace(args=scrub_pii(ctx.args))

agent = Agent(
    model="gpt-4o",
    tools=[lookup_customer],
    hooks={"pre_tool": [pii_scrub]},
)
```

**Ví dụ — block refund > $1000:**

```python
async def refund_guard(ctx: PostToolContext) -> None:
    if ctx.tool_name == "process_refund" and ctx.result["amount"] > 1000:
        raise PermissionError(f"Refund ${ctx.result['amount']} cần approval thủ công")

agent = Agent(model="gpt-4o", tools=[process_refund], hooks={"post_tool": [refund_guard]})
```

**Modes:**
- `sequential` (default): handler chạy nối tiếp, raise → block lifecycle
- `parallel`: fire-and-forget, swallow exception (cho metrics)

📖 Chi tiết: [hooks.md](hooks.md) — 7 cookbook recipes, registration styles.

**So sánh Hook vs Verifier vs Guardrail:**

| Cơ chế | Khi nào | Có retry loop? |
|---|---|---|
| Hook | Bất cứ event nào | Không |
| Verifier | Sau LLM output | Có (EvaluatorStrategy refines) |
| Guardrail | Input + Output | Không (BLOCK ngay) |

---

### 3.3 Reasoning — Formal Verifier (🔲 Phase 14)

Khi LLM output cần **proof** thay vì "có vẻ đúng". Plug vào VerifierPipeline như tier thứ 4.

**Use case:**

```
from ryuu import Agent

# Trading bot — constraint formal hoá được
agent = Agent(
    model="gpt-4o",
    tools=[buy, sell],
    verifiers=["schema", "formal"],     # thêm "formal" → kéo ryuu-reasoning
    reasoning={
        "z3_constraints": """
            (assert (<= position_size 10000))
            (assert (>= cash_reserve 5000))
            (assert (<= correlation 0.5))
        """,
    },
)

result = await agent.run("Buy 100 AAPL at $150")
# Z3 check: 100 * 150 = $15000 > $10000 limit → fail
# EvaluatorStrategy refine: "Reduce to 60 shares ($9000)"
```

**Khi nào dùng:**
- ✅ High-stakes: trading, medical, legal, compliance
- ✅ Constraint formal hoá được (số, rule, pattern)
- ❌ Free-form output (essay, code) → dùng LLMJudge

**Cognitive ≠ Reasoning:**

| | `ryuu-cognitive` (ReAct/CoT) | `ryuu-reasoning` (Z3/Prolog) |
|---|---|---|
| Vai trò | LLM *generate* decision | Solver *verify* decision |
| Logic | Soft (probabilistic) | Hard (mathematical proof) |
| Khi nào | Lúc agent đang nghĩ | Sau khi agent ra quyết định |

Reasoning chạy **sau** Cognitive, không thay thế.

📖 Chi tiết: [Architecture §7.8](../architecture/uaaf-v2-architecture.md#78-reasoning-tier--ryuu-reasoning-rev-3-phase-14).

---

## 4. Multi-Agent Patterns

> Mặc định 1 agent + 1 prompt đủ cho hầu hết use case. Khi cần nhiều agent phối hợp, RYUU có 5 pattern chuẩn — chọn theo *cách dữ liệu chảy*, không phải theo "tôi muốn nhiều agent".

### 4.0 Khi Nào Cần Nhiều Agent?

```
1 input → 1 output                              → 1 agent đủ
1 input → nhiều output song song                → Parallel Fan-out
1 input → output A → input B → output B         → Chaining
input → phân loại → 1 trong N agent             → Routing
input → main agent gọi N worker tuỳ ngữ cảnh    → Orchestrator-Worker
input → output có thể sai → check + retry       → Evaluator-Optimizer
```

**Tránh anti-pattern**: "Có 3 agent vì có 3 nhiệm vụ" — sai. Đúng: "có 3 agent vì 3 nhiệm vụ chạy đồng thời (fan-out) hoặc kế tiếp với checkpoint (chaining)". Nếu chỉ là 3 step trong 1 agent thì viết 3 method, không cần 3 agent.

### 4.0.1 Hai Mức API

| Mức | API | Ai dùng |
|---|---|---|
| **Facade** (🔲 Phase 10.5) | `Chain([...])`, `FanOut(...)`, `Router(...)`, `Orchestrator(...)`, `Evaluator(...)` | 90% — lean, type-safe |
| **Primitive** (✅ shipped) | `AgentPool` + `Task` + `dispatch`/`fan_out`, `WorkflowEngine`, `StrategySelector` | Advanced — custom routing/logic |

Mỗi pattern dưới đây show cả 2:
- ✅ **Now**: code thật từ `examples/` dùng primitive (verbose nhưng đầy đủ)
- 🔲 **Planned**: API facade Phase 10.5 (lean, 1-3 dòng)

Facade chỉ là wrapper — class-based vẫn dùng cùng primitive.

---

### 4.1 Routing — Intent → Strategy → Agent

**Khi nào dùng:** Input có nhiều "loại" và mỗi loại cần xử lý khác nhau.

```
User query
    ↓
IntentAnalyzer        ← rule-based hoặc LLM phân loại
    ↓ StructuredIntent
StrategySelector      ← chọn strategy đầu tiên mà applicable() == True
    ↓
[DirectStrategy] [ReActStrategy] [EvaluatorStrategy] [ParallelStrategy]
    ↓
AgentPool.dispatch(task)
```

**✅ Now — `examples/todo_app` (primitive, class-based)**: 4 strategy + 2 analyzer (rule + LLM):

```python
# examples/todo_app/strategies.py:118
class TodoReActStrategy:
    def applicable(self, intent: StructuredIntent, context: ExecutionContext) -> bool:
        # Hybrid: LLM hint AND business rule
        return (
            intent.suggested_strategy == REACT
            and intent.complexity >= ComplexityLevel.MEDIUM
        )
```

**Hybrid pattern** (LLM hints, code constrains): analyzer LLM trả `suggested_strategy="react"`, nhưng `applicable()` còn check thêm `complexity >= MEDIUM` để không pay react cost cho query trivial.

**🔲 Planned — Phase 10.5 facade:**

```
from ryuu import Agent, Router

router = Router(
    # Cách 1: dict-based — key match intent.intent_type
    routes={
        "report":  Agent(model="gpt-4o",      instructions="Generate JSON breakdown"),
        "analyze": Agent(model="gpt-4o-mini", instructions="Analyze tasks"),
        "_default": Agent(model="gpt-4o-mini"),
    },
    # Cách 2: callable analyzer trả về route key
    analyzer=lambda query: "report" if "json" in query.lower() else "analyze",
    # Cách 3 (advanced): inject IIntentAnalyzer cho LLM-based routing
    # analyzer=LLMIntentAnalyzer(model="gpt-4o-mini"),
)

result = await router.run("Show priority breakdown as JSON")
# → analyzer → "report" → dispatch tới Agent JSON
```

**Refs:**
- `examples/todo_app/intent.py` — `TodoIntentAnalyzer` (rule), `build_llm_analyzer` (LLM)
- `examples/todo_app/strategies.py` — 4 strategy class với `applicable()`
- `examples/todo_app/main.py` — `RequestHandler` + `StrategySelector` wiring

---

### 4.2 Chaining — Output A → Input B (với Checkpoint)

**Khi nào dùng:** Pipeline tuần tự, cần checkpoint để resume khi fail.

```
[State A] ───output───▶ [State B] ───output───▶ [State C]
   │                       │                       │
   └─── checkpoint ─── checkpoint ─── checkpoint ──┘
```

Khác `multi-step trong 1 agent method`: chaining có **WorkflowEngine** ghi state vào `CheckpointStore` sau mỗi state. Crash giữa chừng → resume từ checkpoint cuối, không chạy lại từ đầu.

**✅ Now — `examples/code_analysis` (primitive, WorkflowEngine)**: 3 states `ingest → analyse → summarize`:

```
# examples/code_analysis/workflow.py
workflow = Workflow(states=[
    IngestState(),      # output: list[ClassInfo]
    AnalyseState(),     # input: list[ClassInfo] → output: list[ClassAnalysis]
    SummarizeState(),   # input: list[ClassAnalysis] → output: CodebaseReport
])

# examples/code_analysis/main.py
engine = WorkflowEngine(checkpoint_store=InMemoryCheckpointStore())
result = await engine.run(workflow, initial_input=repo_path, context=ctx)
```

**🔲 Planned — Phase 10.5 facade:**

```
from ryuu import Agent, Chain

# Default: output A (str) → input B (str)
chain = Chain([
    Agent(model="gpt-4o-mini", instructions="Extract entities from text"),
    Agent(model="gpt-4o",      instructions="Summarize entities into 3 bullets"),
    Agent(model="gpt-4o-mini", instructions="Translate bullets to VN"),
])
result = await chain.run("Long article text here...")

# Cần transform giữa các step?  Chain nhận cả Agent VÀ callable trong cùng list.
# Không cần param `transforms=` riêng — đỡ 1 khái niệm phải nhớ.
chain = Chain([
    extract_agent,
    lambda extract_out: json.dumps(extract_out["entities"]),   # pure transform
    summarize_agent,
    str.upper,                                                  # pure transform
    translate_agent,
])

# Checkpoint khi fail? — Pass CheckpointStore qua kwarg, không phải bool magic.
chain = Chain(
    [extract_agent, summarize_agent, translate_agent],
    checkpoint_store=FileCheckpointStore("./ckpt.jsonl"),
)
```

**Tại sao không cần `transforms=` riêng?** Vì Chain chấp nhận callable như "agent" — uniform interface `(input) → output`. Giảm 1 concept, code đọc tự nhiên hơn.

**Tại sao không dùng hook cho transform?** Hook gắn vào *agent* (fires khi agent đó execute). Transform gắn vào *edge* giữa 2 agent trong chain. Nếu dùng hook:
- `post_execute` hook trên A → biến đổi output A *toàn cục* (fires kể cả khi A chạy ngoài chain)
- `pre_execute` hook trên B → B phải biết mình đang trong chain (leaky abstraction)

Callable trong Chain giữ transform *cục bộ* tại chain đó — đúng scope.

**Khi nào dùng `Chain` thay vì gọi 3 method tuần tự?**
- ✅ Mỗi state expensive (LLM call, DB write) — muốn resume
- ✅ Cần inspect intermediate state để debug
- ❌ 3 step nhanh, fail thì retry cả pipeline OK → method call thường

**Refs:** `examples/code_analysis/workflow.py`, `examples/code_analysis/main.py`

---

### 4.3 Parallel Fan-out — 1 Task → N Subtask Concurrent

**Khi nào dùng:** Có N item độc lập, mỗi item cần LLM riêng — chạy song song để giảm latency.

```
1 input
    │
    ├──▶ Task 1 ──▶ Agent ──▶ Result 1  ┐
    ├──▶ Task 2 ──▶ Agent ──▶ Result 2  ├──▶ Aggregate
    └──▶ Task N ──▶ Agent ──▶ Result N  ┘
```

Latency = max(task_i), không phải sum. Cost vẫn = sum.

**Fan-out có 3 variant** tuỳ "cái gì biến thiên":

| Variant | Biến thiên | Cố định | Use case |
|---|---|---|---|
| **1. Data** | N items | 1 agent | Phân tích N goal cùng prompt |
| **2. Agent** | N agents | 1 input | N chuyên gia review 1 input |
| **3. Mixed** | N (agent, task) pairs | — | Pipeline phức tạp, cost optimization |

**✅ Now — Variant 1 (data) — `examples/todo_app`**: 1 query "analyze each goal" → 3 subtask per goal:

```
# examples/todo_app/strategies.py — TodoParallelStrategy.execute
tasks = [
    Task(task_id=f"todo-par-{gid}",
         payload={"query": f"{intent.action} (focus only on goal {gid})", ...})
    for gid in self.GOAL_IDS  # ("g1", "g2", "g3")
]
results = await agent_pool.fan_out(tasks, context, on_error="collect")
combined = "\n\n".join(f"━━ {gid.upper()} ━━\n{r.output}" for gid, r in zip(...))
```

**Trigger:** `applicable()` check `intent.entities["scope"] == "per_entity"` (LLM hint) HOẶC keyword match trong action ("each goal", "separately") — dual check để rule analyzer cũng dùng được.

**✅ Now — Variant 1 — `examples/code_analysis`**: 1 task per class trong codebase:

```
# examples/code_analysis/agents.py:225
tasks = [
    Task(task_id=f"cls-{cls.name}", payload={"class": cls.name})
    for cls in classes  # N classes
]
results = await pool.fan_out(tasks, base_context, on_error="collect")
# on_error="collect" → 1 task fail không kill cả batch
```

**🔲 Planned — Phase 10.5 facade (3 variant):**

```
from ryuu import Agent, FanOut

# Variant 1: Same agent, N data items
fanout = FanOut(
    agent=Agent(model="gpt-4o-mini", instructions="Analyze the goal data"),
    items=["g1", "g2", "g3"],
    template="Focus only on goal {item}",   # format mỗi item thành prompt
)
results = await fanout.run("Analyze each goal separately")

# Variant 2: N specialist agents, same input
fanout = FanOut(
    agents=[
        Agent(name="security", model="gpt-4o", instructions="Audit security issues"),
        Agent(name="perf",     model="gpt-4o", instructions="Find perf bottlenecks"),
        Agent(name="style",    model="gpt-4o-mini", instructions="Check code style"),
    ],
)
results = await fanout.run("def login(user, password): ...")
# → 3 góc nhìn khác nhau trên cùng 1 input

# Variant 3: Explicit (agent, task) pairs — full flexibility
fanout = FanOut(
    pairs=[
        (Agent(model="gpt-4o-mini"),    "Summarize chapter 1"),    # cheap model — easy task
        (Agent(model="gpt-4o"),         "Translate chapter 2"),     # expensive — quality matters
        (Agent(model="claude-sonnet"),  "Critique chapter 3"),      # different provider
    ],
)
results = await fanout.run()
```

**Common params:**
- `on_error="collect"` (default) | `"raise"` | `"skip"`
- `aggregate=callable` — custom join logic (default: list of results)
- Validation: chỉ 1 trong 3 (`items`, `agents`, `pairs`) được set

**Refs:** `examples/code_analysis/agents.py:225`, `examples/todo_app/strategies.py` (TodoParallelStrategy)

---

### 4.4 Orchestrator-Worker — 1 Main Agent Dispatch N Worker

**Khi nào dùng:** Main agent **không biết trước** có bao nhiêu worker (depends on input data). Khác Routing (fixed strategies) và Chaining (fixed states).

```
[Main / Orchestrator]
    │
    ├─ analyze input → discover N items
    ├─ register N WorkerAgent instances vào AgentPool
    ├─ dispatch tasks (sequential hoặc fan_out)
    └─ aggregate results → CodebaseReport
```

**✅ Now — `examples/code_analysis` (class-based)**: `CodebaseAnalysisOrchestrator` discover classes từ source code, tạo 1 `ClassAnalysisAgent` per class:

```python
# examples/code_analysis/agents.py (simplified)
class CodebaseAnalysisOrchestrator:
    async def analyse(self, classes: list[ClassInfo], ctx) -> CodebaseReport:
        pool = AgentPool()
        for cls in classes:
            agent = AgentFactory.build_class_analyser(cls)  # 1 agent per class
            pool.register(agent)

        tasks = [Task(task_id=f"cls-{c.name}", payload={...}) for c in classes]
        results = await pool.fan_out(tasks, ctx, on_error="collect")
        return CodebaseReport.aggregate(results)
```

**🔲 Planned — Phase 10.5 facade:**

```
from ryuu import Agent, Orchestrator

orchestrator = Orchestrator(
    # Main agent — phân tích input, quyết định cần discover/dispatch gì
    main=Agent(
        model="gpt-4o",
        instructions="Plan codebase analysis. Identify classes to review.",
        tools=[scan_repo],   # discover phase
    ),
    # Worker factory — main agent gọi để spawn worker cho mỗi item discovered
    workers=lambda item: Agent(
        model="gpt-4o-mini",
        instructions=f"Analyze class {item['name']}: security, perf, style",
    ),
    # Aggregation — gộp kết quả worker thành output cuối
    aggregate=lambda results: CodebaseReport.from_analyses(results),
)

report = await orchestrator.run("Analyze /path/to/repo")
```

**Khi nào dùng Orchestrator-Worker thay vì chỉ Fan-out?**
- Orchestrator có **discover phase**: input → N (chưa biết N trước khi đọc data)
- Worker **đặc thù**: mỗi worker config khác (prompt, tool, model) — không chỉ payload khác
- Có **aggregation logic phức tạp**: không chỉ join string, mà tính score/dedupe/rank

Nếu N cố định và mỗi worker giống nhau → chỉ cần `FanOut`, không cần `Orchestrator`.

**Refs:** `examples/code_analysis/agents.py` (CodebaseAnalysisOrchestrator, AgentFactory), `examples/code_analysis/main.py`

---

### 4.5 Evaluator-Optimizer — Generate → Verify → Refine

**Khi nào dùng:** Output có thể sai (sai JSON, sai constraint), muốn check + retry tự động với feedback.

```
[Generator Agent] ──output──▶ [Verifier] ──┐
                                  │         │
                              passed?       │
                                  │         │
                       ┌──────────┴──────┐  │
                      yes                no  │
                       │                 │   │
                   return            refine  │
                                     prompt  │
                                     + retry ◀
```

Khác Hook (`post_llm` block): Evaluator có **retry loop** tự động với feedback inject vào prompt next round.

**✅ Now — `examples/todo_app` (class-based)**: dispatch → check JSON shape → refine nếu invalid:

```
# examples/todo_app/strategies.py — TodoEvaluatorStrategy.execute
class TodoEvaluatorStrategy:
    def applicable(self, intent, context) -> bool:
        return intent.intent_type == "report"   # routing predicate

    async def execute(self, intent, context, agent_pool, verifier):
        # Round 1: generate
        result = await agent_pool.dispatch(task, context)
        if _looks_like_json(str(result.output)):
            return CognitiveResult(content=result.output, confidence=0.95, ...)

        # Round 2: refine với feedback
        refined_task = Task(payload={
            "query": intent.action + " — Return ONLY valid JSON, no prose.",
            "prompt": prompt_name,
        })
        refined = await agent_pool.dispatch(refined_task, context)
        return CognitiveResult(content=refined.output, confidence=0.70, ...)
```

**🔲 Planned — Phase 10.5 facade:**

```
from ryuu import Agent, Evaluator

# Built-in verifier — JSON shape
evaluator = Evaluator(
    generator=Agent(model="gpt-4o", instructions="Return priority breakdown"),
    verifier="json_schema",                     # or "schema", "llm_judge", "formal"
    schema={"by_priority": dict, "totals": dict},
    max_refines=2,
    refine_hint="Return ONLY valid JSON, no prose.",
)
result = await evaluator.run("Show task priorities")

# Custom verifier callable
async def is_valid(output: str) -> tuple[bool, str]:
    if "SELECT" in output.upper():
        return False, "Avoid SQL keywords"
    return True, ""

evaluator = Evaluator(
    generator=Agent(model="gpt-4o"),
    verifier=is_valid,           # callable returns (passed, feedback)
    max_refines=3,
)

# Plug ryuu-reasoning (Z3) as verifier
evaluator = Evaluator(
    generator=Agent(model="gpt-4o", tools=[buy, sell]),
    verifier="formal",
    constraints={"position_size": "<= 10000", "cash_reserve": ">= 5000"},
    max_refines=2,
)
```

**Verifier tier mạnh hơn:** Trong `ryuu-cognitive`, có thể plug `VerifierPipeline` (Schema → LLMJudge → GroundTruth → Formal Z3) thay vì check JSON tự code. Verifier trả `VerifierResult(passed, confidence, feedback)` — Evaluator dùng `feedback` để refine.

**Refs:** `examples/todo_app/strategies.py` (TodoEvaluatorStrategy), `packages/ryuu-cognitive/src/ryuu_cognitive/verifier.py`

---

### 4.6 Pattern Combination — Real World

Code_analysis kết hợp **3 pattern cùng lúc**:
1. **Chaining**: Workflow 3 state (ingest → analyse → summarize)
2. **Orchestrator-Worker**: AnalyseState dùng CodebaseAnalysisOrchestrator
3. **Parallel Fan-out**: Orchestrator gọi `pool.fan_out` cho N classes

```
WorkflowEngine.run(workflow)
    │
    ├─ State 1: IngestState           (Chaining)
    │    └─ scan repo → list[ClassInfo]
    │
    ├─ State 2: AnalyseState          (Chaining)
    │    └─ CodebaseAnalysisOrchestrator  (Orchestrator-Worker)
    │         └─ pool.fan_out(N tasks)    (Parallel Fan-out)
    │              └─ N × ClassAnalysisAgent
    │
    └─ State 3: SummarizeState        (Chaining)
         └─ aggregate N analyses → CodebaseReport
```

Todo_app kết hợp **3 pattern khác**:
1. **Routing**: IntentAnalyzer → StrategySelector
2. **Parallel Fan-out**: TodoParallelStrategy → 3 goals concurrent
3. **Evaluator-Optimizer**: TodoEvaluatorStrategy → verify JSON + refine

**Bài học:** Đừng pick 1 pattern. Compose theo *cách dữ liệu chảy*. Code_analysis có "data flow tuần tự với 1 step parallel" → Chain + Orchestrator + Fan-out. Todo_app có "query đa dạng cần phân loại" → Routing + nội tại từng strategy là 1 pattern khác.

**🔲 Planned — Phase 10.5 facade composability:**

```
from ryuu import Agent, Chain, FanOut, Router, Orchestrator, Evaluator

# Code analysis flow — nest facade
pipeline = Chain([
    Agent(model="gpt-4o-mini", instructions="Scan repo, list classes", tools=[scan_repo]),
    Orchestrator(
        main=Agent(model="gpt-4o", instructions="Plan analysis per class"),
        workers=lambda cls: Agent(model="gpt-4o-mini", instructions=f"Audit {cls}"),
    ),
    Agent(model="gpt-4o", instructions="Summarize all class audits into report"),
])
report = await pipeline.run("/path/to/repo")

# Todo app flow — Router → nested patterns per route
app = Router(
    routes={
        "report": Evaluator(
            generator=Agent(model="gpt-4o", instructions="Generate JSON"),
            verifier="json_schema",
        ),
        "per_entity": FanOut(
            agent=Agent(model="gpt-4o-mini"),
            items=["g1", "g2", "g3"],
            template="Analyze goal {item}",
        ),
        "_default": Agent(model="gpt-4o-mini"),
    },
    analyzer=intent_analyzer,
)
result = await app.run(query)
```

**Mỗi facade implement cùng interface `.run(input) → output`** → nest tự do, không vendor-specific glue code.

---

### 4.7 Handoff — Define Input/Output Giữa Agents

Khi nhiều agent nối nhau, câu hỏi cốt lõi: **output của A định dạng gì? B mong đợi gì?** RYUU có 3 mức define handoff, từ implicit → explicit.

#### Mức 1: Default — String Passthrough (zero config)

Output `str` của A → input `str` của B. Không cần khai báo gì.

```python
chain = Chain([extract_agent, summarize_agent])
# A.output (str) → B.input (str), tự động
```

**Dùng khi:** Cả 2 agent giao tiếp bằng text tự nhiên. ~70% case.

#### Mức 2: Structured Output — Pydantic Model (declare ở Agent)

Khi consumer cần dữ liệu **cấu trúc**, declare `output_type` ở producer + (optional) `input_type` ở consumer:

```python
from pydantic import BaseModel
from ryuu import Agent, Chain

class Entities(BaseModel):
    people: list[str]
    locations: list[str]
    dates: list[str]

extract_agent = Agent(
    model="gpt-4o-mini",
    instructions="Extract entities. Return JSON matching schema.",
    output_type=Entities,                # ← producer declares
)

summarize_agent = Agent(
    model="gpt-4o",
    instructions="Summarize entities into 3 bullets",
    input_type=Entities,                 # ← consumer declares (IDE check)
)

chain = Chain([extract_agent, summarize_agent])
# Framework: parse output A as JSON → Entities → pass vào B
# B nhận ctx.input.people, ctx.input.locations, ...
```

**Dùng khi:** Cần type safety, IDE autocomplete, validation tự động.

#### Mức 3: Custom Transform — Callable trong Chain (edge-level)

Khi transform chỉ có ý nghĩa **trong chain cụ thể này** (không reuse):

```python
chain = Chain([
    extract_agent,
    lambda ents: {"top_3": ents.people[:3]},   # transform — pure function
    summarize_agent,
])
```

**Dùng khi:** Logic edge-specific, không thuộc về agent nào.

#### Cho Pattern Khác — Handoff Define Ở Đâu

| Pattern | Handoff define ở đâu |
|---|---|
| **Chain** | Default str OR `output_type=` OR callable trong list |
| **FanOut** | `aggregate=callable` — gộp N output thành 1 |
| **Router** | `analyzer` decide route; output passthrough (không gộp) |
| **Orchestrator** | `aggregate=callable` gộp workers → main; có thể có `handoff_tool` để worker giao việc lại |
| **Evaluator** | `verifier` trả `(passed, feedback)`; feedback inject vào generator prompt next round |

#### Ví dụ — Orchestrator với explicit handoff

```python
class WorkerOutput(BaseModel):
    findings: list[str]
    severity: int

orchestrator = Orchestrator(
    main=Agent(
        model="gpt-4o",
        instructions="Plan codebase analysis, dispatch workers",
        output_type=AnalysisPlan,               # main declares plan format
    ),
    workers=lambda item: Agent(
        model="gpt-4o-mini",
        instructions=f"Audit {item['name']}",
        output_type=WorkerOutput,               # each worker declares
    ),
    aggregate=lambda outputs: CodebaseReport(   # explicit: workers → final
        total_issues=sum(len(o.findings) for o in outputs),
        max_severity=max(o.severity for o in outputs),
    ),
)
```

#### Quy Tắc Chọn

```
1. Start: default string passthrough (Mức 1)
2. Khi consumer cần data có schema → declare output_type (Mức 2)
3. Khi transform chỉ cục bộ trong chain → callable (Mức 3)
4. Khi N → 1 (FanOut/Orchestrator) → aggregate=callable
```

**Anti-pattern:** Đừng dùng hook `post_execute` để transform output của A trước khi pass cho B. Hook gắn vào *agent* (fires kể cả khi A chạy ngoài chain) — leak abstraction. Transform thuộc về *edge*, dùng callable trong Chain hoặc `output_type`.

---

### 4.8 Quyết Định Nhanh

| Câu hỏi | Pattern |
|---|---|
| Input có nhiều loại, mỗi loại logic khác? | Routing |
| N item độc lập cần xử lý? | Parallel Fan-out |
| Pipeline có expensive step muốn checkpoint? | Chaining |
| Main agent cần discover N worker từ input? | Orchestrator-Worker |
| Output có thể sai, cần auto-retry với feedback? | Evaluator-Optimizer |
| Chỉ là 3 step gọi LLM tuần tự, không expensive? | Không pattern — viết 3 method trong 1 agent |

---

## 5. Prompt + Tool Modularization (Per-Product Structure)

> Mỗi product (todo_app, code_analysis, stock_advisory) có **convention chung** để tách prompt khỏi code và tool schema khỏi handler. Áp dụng để codebase mở rộng không thành mớ hỗn độn.

### 5.1 Cấu Trúc Folder Chuẩn

```
my_product/
├── __init__.py
├── agent.py           ← Class kế thừa LLMAgent/BaseAgent + business logic
├── strategies.py      ← ICognitiveStrategy nếu cần multi-strategy routing
├── intent.py          ← IIntentAnalyzer (rule + LLM analyzer)
├── tools.py           ← ToolRegistry với handler thật (Python callable)
├── models.py          ← Domain dataclasses (Goal, Task, ClassInfo, ...)
├── main.py            ← Wire everything: RuntimeConfig → RYUURuntime → handle()
├── server.py          ← (Optional) FastAPI/SSE serving
└── prompts/
    └── my_product/
        ├── v1.yaml    ← Prompt templates + tool schema (versioned)
        └── v2.yaml    ← Khi thay prompt structure → bump version
```

**Áp dụng cho** todo_app, code_analysis, stock_advisory — đều theo cấu trúc này.

### 5.2 Prompts — YAML Versioned

**Primitives của ryuu:**
- `PromptRegistry` (`ryuu.prompts.registry`) — load + cache YAML, render `CompletionRequest`
- `PromptConfig`, `PromptTemplate`, `ToolDefinition` — dataclass models cho YAML
- Convention path: `{prompts_root}/{project}/{version}.yaml`

**Lý do tách YAML:** Prompt thay đổi liên tục mà không cần redeploy code. Version để A/B test, rollback.

#### Structure: System vs User vs Few-shot

Mỗi prompt template có 3 phần — chỗ đặt khác nhau:

```yaml
prompts:
  analyze:
    # ── SYSTEM: persona + rules + context ───────────────────
    # Bất biến giữa các turn. Nên chứa: role, rules, output format, RAG context
    system: |
      You are a productivity analyst.
      Rules:
      - Always cite goal_id when referencing tasks
      - Output max 200 words
      Format: bullet list with rationale.

      === PORTFOLIO DATA (RAG injected) ===
      {context}                                # ← variable từ assembler
      === END DATA ===

    # ── FEW-SHOT: optional examples ─────────────────────────
    # Giúp LLM hiểu output format khi system prompt không đủ rõ
    examples:
      - user: "Show me blockers for sprint 5"
        assistant: |
          - g1: Deploy blocker — CI red since 2d
          - g2: API spec pending review (3d old)
      - user: "Why is g2 behind?"
        assistant: |
          - Effort ratio 1.7x — under-estimated DB migration
          - Tasks t12, t13 awaiting approval

    # ── USER: template cho input runtime ────────────────────
    # Cái user gõ thật sẽ thay {query}
    user: "{query}"
```

#### Nơi đặt từng loại data

| Loại data | Đặt ở đâu | Lý do |
|---|---|---|
| **Persona/role** | `system` | Bất biến — chỉ load 1 lần per session |
| **Hard rules** ("Never X", "Always Y") | `system` | LLM tuân thủ tốt hơn khi ở đầu context |
| **Output format spec** | `system` | Cần kèm example nếu format phức tạp |
| **Static RAG context** (docs, code) | `system` `{context}` | Cached prompt prefix → giảm cost |
| **Few-shot examples** (1-5 cases) | `examples` array | Khi system prompt không đủ rõ về format |
| **User query runtime** | `user` `{query}` | Variable nhỏ, thay đổi mỗi turn |
| **Conversation history** | Append vào messages array (không YAML) | Quá dài, không version được |
| **Tool results** | Append role="tool" message | Framework tự handle qua ReAct loop |

#### Anti-pattern Prompt

- ❌ Nhồi user query vào system prompt → mất prompt caching, không tách được examples
- ❌ Put RAG context vào user prompt → LLM coi như user input, không trust như rules
- ❌ Few-shot examples > 5 → overfit, increase cost. Dùng RAG retrieval thay
- ❌ Trộn 3 use case vào 1 prompt (`if intent == X else Y`) → tách thành 3 prompt template trong cùng YAML

```yaml
# examples/todo_app/prompts/todo_app/v1.yaml
version: "1.0"
description: "Todo app — productivity analysis agent"
model: "gpt-4o-mini"
temperature: 0.1
max_tokens: 1024

prompts:
  analyze:                              # ← prompt_name (gọi qua registry.build_request)
    system: |
      You are a productivity analyst...
      === PORTFOLIO DATA ===
      {context}                         # ← variables injected runtime
      === END DATA ===
    user: "{query}"

  priority_breakdown:                   # ← prompt khác trong cùng product
    system: |
      Return ONLY valid JSON...
    user: "{query}"

tools:                                  # ← tool SCHEMA (LLM sees this)
  - name: get_task_stats
    description: "Get completion stats for a goal"
    parameters:
      type: object
      properties:
        goal_id: {type: string}
      required: [goal_id]
```

**Load qua PromptRegistry:**

```python
# examples/todo_app/agent.py
from ryuu.prompts.registry import PromptRegistry

_PROMPTS_ROOT = Path(__file__).parent / "prompts"
_registry = PromptRegistry(prompts_root=_PROMPTS_ROOT)

# Load + build request
cfg = _registry.load("todo_app", version="v1")
request = _registry.build_request(
    cfg,
    prompt_name="analyze",         # chọn template trong YAML
    include_tools=True,            # inject tool schema vào request
    context=assembled_memory,      # variable trong template
    query="Show priority breakdown",
)
```

**Lợi ích:**
- Prompt engineer sửa YAML, không đụng Python
- A/B test: load `v1` vs `v2` qua config
- 1 registry serve nhiều product (`todo_app/v1`, `code_analysis/v1`)

### 5.3 Tools — Schema (YAML) vs Handler (Python)

**Primitives của ryuu (`ryuu_execution.tool_registry`):**

```python
@runtime_checkable
class ITool(Protocol):
    """Tool contract — handler implements this OR ToolRegistry wraps callable."""
    tool_id: str
    schema: dict[str, Any] | None
    async def execute(self, args: dict[str, Any]) -> Any: ...

class ToolRegistry:
    def register(
        self,
        name: str,
        tool: ITool | Callable[..., Awaitable[Any]],   # accept cả ITool VÀ async function
        allowed_domains: set[str] | None = None,        # per-tool security
    ) -> None: ...

    async def run(self, tool_call: dict, domain: str = "") -> str: ...
    async def run_all(self, tool_calls: list[dict], domain: str = "") -> list[dict]: ...
```

**2 cách register tool:**

```python
# Cách 1 — callable (đơn giản, đa số case)
async def get_task_stats(goal_id: str) -> dict:
    return {"total": 10, "completed": 7}

registry.register("get_task_stats", get_task_stats)

# Cách 2 — ITool class (khi tool có state hoặc schema phức tạp)
class DBQueryTool:
    tool_id = "db_query"
    schema = {"type": "object", "properties": {"sql": {"type": "string"}}}

    def __init__(self, db_pool):       # state: connection pool
        self._db = db_pool

    async def execute(self, args: dict) -> Any:
        return await self._db.fetch(args["sql"])

registry.register("db_query", DBQueryTool(db_pool=...))
```

**`allowed_domains` — per-tool security:**

```python
# Tool nhạy cảm — chỉ cho domain trading dùng, todo_app không touch được
registry.register(
    "execute_trade",
    execute_trade_handler,
    allowed_domains={"stock_advisory", "portfolio"},
)
# Agent thuộc domain "todo_app" gọi "execute_trade" → PermissionError
```

**Nguyên tắc:** YAML định nghĩa **schema** (LLM thấy gì), Python implement **handler** (thực thi thật).

```python
# examples/todo_app/tools.py
from ryuu_execution import ToolRegistry

def build_todo_registry(goals: list[Goal], tasks: list[Task]) -> ToolRegistry:
    """Wire handler với access vào loaded data (DI pattern)."""
    registry = ToolRegistry()
    goal_map = {g.goal_id: g for g in goals}

    async def get_task_stats(goal_id: str, status_filter: str = "all") -> dict:
        """Handler — chạy thật khi LLM call tool."""
        target = goal_map[goal_id].tasks if goal_id != "all" else list(tasks)
        if status_filter != "all":
            target = [t for t in target if t.status == status_filter]
        return {"total": len(target), "completed": sum(1 for t in target if t.status=="completed")}

    registry.register("get_task_stats", get_task_stats)
    # ... thêm các tool khác
    return registry
```

**Vì sao tách:**
- Schema (YAML) là **contract với LLM** — text, không có behavior
- Handler (Python) cần **closure over data** (goal_map, db connection, ...)
- LLM provider nâng cấp schema format (JSON Schema → MCP) → chỉ sửa YAML loader, handler giữ nguyên

### 5.4 Wiring — main.py

```python
# examples/todo_app/main.py (simplified)
async def main():
    goals, tasks = load_demo_data()

    # 1. Build tool registry với DI
    tool_registry = build_todo_registry(goals, tasks)

    # 2. Build agent (prompt + tool injected qua factory)
    agent = TodoAnalysisAgent(
        agent_id="todo-analyst",
        llm=build_provider(),
        tool_registry=tool_registry,
        prompt_version="v1",        # ← chọn version YAML
        cost_tracker=RealCostTracker(...),
        audit_logger=FileAuditLogger(...),
    )
    await agent.ingest_goals(goals, scope_key="demo")

    # 3. Build runtime (intent → strategy → agent)
    runtime = RYUURuntime(
        agents={"todo-analyst": agent},
        analyzer=build_llm_analyzer(...),
        strategies=[TodoEvaluatorStrategy(), TodoParallelStrategy(),
                   TodoReActStrategy(), TodoDirectStrategy()],
    )

    # 4. Handle requests
    response = await runtime.handle(message="Show priority breakdown", scope=...)
```

### 5.5 So Sánh 3 Product

| | todo_app | code_analysis | stock_advisory |
|---|---|---|---|
| **Patterns** | Routing + Evaluator + Fan-out | Chain + Orchestrator + Fan-out | Direct + Verifier (audit chain) |
| **Prompts** | `prompts/todo_app/v1.yaml` | `prompts/code_analysis/v1.yaml` | `prompts/stock/v1.yaml` |
| **Tool count** | 3 (stats, search, filter) | 2 (scan_repo, read_file) | 5 (price, news, analyst, ...) |
| **Trust level** | LOW (read-only analysis) | MEDIUM (file system access) | HIGH (financial decision) |
| **Verifier** | JSON shape (Evaluator) | None | LLMJudge + GroundTruth + AuditLogger |
| **Workflow** | Stateless | WorkflowEngine (3 states) | Stateless |
| **Memory backbone** | MemoryBackbone (session) | None (per-run) | EpisodicMemoryStore (track signals) |

**Khuôn mẫu chung:**
1. Domain models (`models.py`) — Pydantic/dataclass cho entity
2. Prompts (`prompts/*/v1.yaml`) — versioned templates + tool schema
3. Tools (`tools.py`) — handler factory `build_X_registry(deps) -> ToolRegistry`
4. Agent (`agent.py`) — extend `LLMAgent` cho prompt loading, ReAct loop, model tier selection
5. Strategies (`strategies.py`) — chỉ khi cần multi-strategy routing (todo_app)
6. Workflow (`workflow.py`) — chỉ khi cần chained states với checkpoint (code_analysis)
7. Wiring (`main.py`) — DI assembly

### 5.6 Khi Nào Tách Thêm

| Symptom | Tách thêm |
|---|---|
| YAML > 200 dòng | Split: `analyze.yaml`, `report.yaml`, `tools.yaml` |
| `tools.py` > 500 dòng | Split: `tools/data.py`, `tools/external_api.py`, `tools/__init__.py` |
| Nhiều agent class | `agents/analyst.py`, `agents/orchestrator.py` |
| Domain phức tạp | Thêm `services/` cho business logic non-LLM |
| 2+ environment | Thêm `config/dev.yaml`, `config/prod.yaml` |

**Quy tắc:** Đừng tách sớm. Start với cấu trúc §5.1, tách khi 1 file vượt 300-500 dòng hoặc gây merge conflict.

### 5.7 Prompt Versioning — Lifecycle v1 → v2

Prompt thay đổi liên tục (LLM mới, format khác, A/B test). Cần versioning để không break production khi thử nghiệm.

#### Quy tắc bump version

| Thay đổi | Bump |
|---|---|
| Sửa typo, đổi từ ngữ | Không bump — sửa thẳng v1 |
| Thêm prompt mới vào file | Không bump — thêm vào v1 |
| Đổi `{variables}` template | **Bump v2** — break consumer code |
| Thêm/xoá tool | **Bump v2** — agent behavior đổi |
| Đổi model default | **Bump v2** — cost/quality khác |
| Đổi structure system prompt | **Bump v2** — quality regression risk |

#### Workflow v1 → v2

```
prompts/todo_app/
├── v1.yaml         ← production (đang dùng)
├── v2.yaml         ← draft (đang test)
└── _archive/
    └── v0.yaml     ← deprecated, giữ để debug history
```

**Step-by-step (KHÔNG sửa code, chỉ config/flag):**

```bash
# Step 1: Copy v1 → v2, sửa nội dung YAML
cp prompts/todo_app/v1.yaml prompts/todo_app/v2.yaml
# edit prompts/todo_app/v2.yaml
```

```python
# Step 2: Test v2 trên dev env qua eval (run once, không deploy)
# scripts/compare_versions.py
eval_v1 = EvalRunner(prompt_version="v1").run(suite="todo_smoke")
eval_v2 = EvalRunner(prompt_version="v2").run(suite="todo_smoke")
assert eval_v2.accuracy >= eval_v1.accuracy * 0.95   # không regress > 5%
```

```python
# Step 3: Canary rollout — KHÔNG sửa code agent.
# Code agent đã viết 1 lần, đọc version từ config/flag (xem §5.14).
#
# Cách A — Feature flag (recommended cho prod):
#   Dashboard set "todo-prompt-version" → 10% v2, 90% v1
#   Code không đổi:
async def handle_request(user_id: str, query: str):
    version = ld.variation("todo-prompt-version", user={"key": user_id}, default="v1")
    agent = TodoAnalysisAgent(prompt_version=version)
    return await agent.execute(...)

# Cách B — Config file với percentage (dev/staging):
#   config/prod.yaml:
#     todo_app:
#       prompt_version_canary:
#         v2: 0.1     # 10% traffic
#         v1: 0.9     # 90% traffic
#   Code không đổi sau lần đầu wire:
import random
def pick_version(weights: dict[str, float]) -> str:
    versions, probs = zip(*weights.items())
    return random.choices(versions, weights=probs, k=1)[0]

version = pick_version(config["todo_app"]["prompt_version_canary"])
agent = TodoAnalysisAgent(prompt_version=version)
```

```bash
# Step 4: Full rollout — đổi config/flag, KHÔNG deploy code
# Feature flag: set "todo-prompt-version" → 100% v2 (qua dashboard)
# Hoặc config file:
#   todo_app:
#     prompt_version: v2     # bỏ canary, set thẳng
# → reload config (hoặc restart, tuỳ implementation), code agent không đổi
```

```bash
# Step 5: Archive v1 (sau 30 ngày stable, không có rollback request)
mv prompts/todo_app/v1.yaml prompts/todo_app/_archive/
```

**Quy tắc vàng:** Viết agent **1 lần** với `prompt_version` đọc từ config/flag (§5.14 Cách 2 hoặc 4). Sau đó canary/rollout/rollback chỉ là đổi config — **không bao giờ đụng code agent**.

**Lưu ý:** Không xoá version cũ ngay — giữ ít nhất 30 ngày để rollback nếu phát hiện regression chậm.

### 5.8 Thêm Tool Mới — Checklist 6 Bước

Khi thêm 1 tool vào todo_app (vd: `search_tasks_by_tag`):

```
1. ✅ Define schema vào YAML
2. ✅ Implement handler vào tools.py
3. ✅ Register handler vào ToolRegistry factory
4. ✅ Test handler isolation (không cần LLM)
5. ✅ Test agent với tool (integration test)
6. ✅ Update CHANGELOG.md / prompt version
```

**Step 1 — YAML schema:**

```yaml
# prompts/todo_app/v1.yaml — append vào `tools:` array
tools:
  # ... existing tools
  - name: search_tasks_by_tag
    description: >
      Find tasks matching one or more tags.
      Returns list of task IDs with title + status.
    parameters:
      type: object
      properties:
        tags:
          type: array
          items: {type: string}
          description: "List of tags to match (OR semantics)"
        limit:
          type: integer
          default: 10
      required: [tags]
```

**Step 2 — Handler:**

```python
# tools.py
def build_todo_registry(goals, tasks):
    registry = ToolRegistry()
    # ... existing handlers

    async def search_tasks_by_tag(tags: list[str], limit: int = 10) -> dict:
        matched = [t for t in tasks if any(tag in t.tags for tag in tags)]
        return {
            "matches": [
                {"task_id": t.task_id, "title": t.title, "status": t.status}
                for t in matched[:limit]
            ],
            "total": len(matched),
        }

    registry.register("search_tasks_by_tag", search_tasks_by_tag)
    return registry
```

**Step 3-4 — Test handler standalone:**

```python
# tests/test_tools.py
async def test_search_tasks_by_tag():
    registry = build_todo_registry(demo_goals(), demo_tasks())
    handler = registry.get("search_tasks_by_tag")
    result = await handler(tags=["backend"], limit=5)
    assert result["total"] >= 1
    assert all("backend" in t.get("tags", []) for t in result["matches"])
```

**Step 5 — Integration test (agent thực sự gọi tool):**

```python
async def test_agent_uses_new_tool():
    agent = TodoAnalysisAgent(prompt_version="v1", tool_registry=registry)
    result = await agent.execute(
        Task(payload={"query": "Find tasks tagged backend", "prompt": "analyze"}),
        ctx,
    )
    # Verify agent called tool (qua audit log hoặc cost tracker)
    assert agent.audit_logger.tool_calls[-1] == "search_tasks_by_tag"
```

**Step 6 — Document:**

```markdown
# CHANGELOG.md
## [Unreleased]
### Added
- todo_app: `search_tasks_by_tag` tool for tag-based task discovery
```

### 5.9 Prompt Management — Best Practices

| Practice | Lý do |
|---|---|
| **1 prompt = 1 use case** | Đừng cố cover nhiều task trong 1 system prompt — split thành `analyze`, `report`, `next_sprint` |
| **Variables explicit (`{context}`, `{query}`)** | Không hard-code data — registry inject runtime |
| **Tool schema cùng file YAML** | LLM thấy gì = YAML chứa gì — 1 source of truth |
| **Test prompt qua eval suite** | Đo accuracy/cost trước khi rollout, không chỉ "có vẻ tốt" |
| **Pin model trong YAML** | `model: "gpt-4o-mini"` — không để runtime pick random |
| **`temperature` thấp cho structured output** | 0.0-0.2 cho JSON; 0.7+ cho creative writing |
| **Comment trong YAML** | YAML support `# comment` — note tại sao chọn prompt structure đó |

### 5.10 Tool Management — Best Practices

| Practice | Lý do |
|---|---|
| **Handler async** | Block event loop = drop QPS. Even file I/O dùng `aiofiles` |
| **Handler return `dict` JSON-serializable** | LLM cần parse output để decide next action |
| **Tên tool snake_case ngắn gọn** | `get_user_email` ≫ `fetchUserEmailAddressByCustomerId` |
| **Description nói rõ "khi nào dùng + trả gì"** | LLM dùng description để chọn tool — verbose mode |
| **Error → return error dict, đừng raise** | `{"error": "Unknown goal_id"}` — LLM xử lý được; raise → kill task |
| **DI qua factory `build_X_registry(deps)`** | Test/mock dễ, không global state |
| **Sandbox cho tool có side effect** | `SandboxManager` cho exec code, file write — tránh agent xoá nhầm |

### 5.11 Ryuu Primitives — Quick Reference

Khi tự build product, đây là primitive cần biết và file chứa:

| Concern | Primitive | Package | Notes |
|---|---|---|---|
| **Prompt loading** | `PromptRegistry` | `ryuu.prompts.registry` | YAML versioned, cache in-memory |
| **Prompt models** | `PromptConfig`, `PromptTemplate`, `ToolDefinition` | `ryuu.prompts.models` | Dataclass cho YAML structure |
| **Build LLM request** | `registry.build_request(cfg, prompt_name, **vars)` | `ryuu.prompts.registry` | Render template + inject vars + attach tools |
| **Tool protocol** | `ITool` | `ryuu_execution.tool_registry` | `tool_id`, `schema`, `async execute(args)` |
| **Tool registry** | `ToolRegistry` | `ryuu_execution.tool_registry` | `register()`, `run()`, `allowed_domains` |
| **Agent base** | `BaseAgent` | `ryuu_execution.agent` | Template method `execute()`, override `_execute()` |
| **LLM agent (with ReAct loop)** | `LLMAgent` | `ryuu_execution.llm_agent` | Extends BaseAgent + `_react_loop()` + `select_model()` |
| **Multi-agent pool** | `AgentPool` | `ryuu_execution.pool` | `register()`, `dispatch()`, `fan_out()` |
| **Sandbox** | `SandboxManager` | `ryuu_execution.sandbox` | Subprocess isolation cho tool nguy hiểm |
| **LLM provider** | `ILLMProvider`, adapters | `ryuu_providers.llm`, `ryuu_providers.adapters.*` | OpenAI, Anthropic |
| **Embedder** | `IEmbedder` | `ryuu_providers.embedders` | Cho RAG/memory |
| **Cost tracking** | `RealCostTracker`, `CostPolicy` | `ryuu_observability.cost` | Per-scope budget enforcement |
| **Audit log** | `FileAuditLogger`, `JSONAuditLogger` | `ryuu_observability.audit` | JSONL hash chain |
| **Tracer** | `OTelTracer` | `ryuu_observability.tracer` | OpenTelemetry spans |
| **Rate limit** | `TokenBucketRateLimiter` | `ryuu_observability.rate_limit` | Per-scope, async |
| **Knowledge backbone** | `IKnowledgeBackbone`, `MemoryBackbone`, `HybridBackbone` | `ryuu_knowledge_base`, `ryuu_knowledge_memory`, `ryuu_knowledge` | Composable |
| **Context assembler** | `ContextAssembler` | `ryuu_knowledge_base` | Token budget trim for prompt |
| **Workflow** | `WorkflowEngine`, `Workflow`, `IState` | `ryuu_workflow.engine`, `ryuu_workflow.state_machine` | Checkpoint resume |
| **Intent analyzer** | `IIntentAnalyzer`, `LLMIntentAnalyzer` | `ryuu.intent.analyzer` | Rule + LLM analyzer |
| **Strategy** | `ICognitiveStrategy`, `StrategySelector` | `ryuu_cognitive.strategy` | Direct/ReAct/Evaluator/Parallel |
| **Verifier** | `IVerifier`, `VerifierPipeline` | `ryuu_cognitive.verifier` | Schema/LLMJudge/GroundTruth |
| **Runtime facade** | `RYUURuntime`, `RequestHandler` | `ryuu_runtime.runtime`, `ryuu_runtime.handler` | Wire all tiers, single entry point |
| **Streaming** | `StreamManager` | `ryuu_runtime.streaming` | SSE / QueueCallbacks |

**Coverage matrix theo example:**

| Example | Primitives dùng |
|---|---|
| **todo_app** | `LLMAgent` + `PromptRegistry` + `ToolRegistry` + `AgentPool` + `StrategySelector` + 4 `ICognitiveStrategy` + `MemoryBackbone` + `ContextAssembler` + `RequestHandler` |
| **code_analysis** | `BaseAgent` + `PromptRegistry` + `WorkflowEngine` + 3 `IState` + custom `Orchestrator` + `AgentPool.fan_out` |
| **stock_advisory** | `LLMAgent` + `PromptRegistry` + `ToolRegistry` + `VerifierPipeline` + `FileAuditLogger` (compliance trail) |

### 5.12 Responsibility Split — RYUU vs Product

Để rõ ai chịu trách nhiệm gì, đây là phân chia chính xác:

#### Prompts

| Việc | RYUU làm sẵn | Product phải làm |
|---|---|---|
| Parse YAML format | ✅ `PromptRegistry._parse()` | — |
| Validate schema (`system`, `user`, `tools`) | ✅ `PromptConfig` dataclass | — |
| Cache config in-memory | ✅ `PromptRegistry._cache` | — |
| Resolve file path theo convention | ✅ `{root}/{project}/{version}.yaml` | Set `prompts_root` |
| Render template variables (`{context}`, `{query}`) | ✅ `.build_request(**vars)` | Pass values vào kwargs |
| Build `CompletionRequest` (messages + tools) | ✅ `.build_request()` | — |
| **Viết nội dung prompt** | ❌ | ✅ Domain expertise — product owns |
| **Chọn version** (v1, v2) khi load | ❌ | ✅ Pass qua kwarg/config |
| **Define variables** template cần | ❌ | ✅ Convention với assembler |

#### Tools

| Việc | RYUU làm sẵn | Product phải làm |
|---|---|---|
| `ITool` Protocol định nghĩa | ✅ `ryuu_execution.tool_registry` | — |
| Wrap callable → ITool | ✅ `_CallableWrapper` tự động | — |
| Tool dispatch loop | ✅ `ToolRegistry.run()` + `run_all()` | — |
| Security check (`allowed_domains`) | ✅ `_check_domain()` | Pass `allowed_domains=` khi register |
| Error handling (try/except, return JSON error) | ✅ trong `.run()` | — |
| ReAct tool calling loop | ✅ `LLMAgent._react_loop()` | — |
| Parse LLM tool_call format | ✅ trong `.run()` | — |
| **Implement handler logic** | ❌ | ✅ Business code |
| **Tool schema (JSON Schema)** | ❌ | ✅ Trong YAML hoặc `ITool.schema` |
| **Register handlers vào registry** | ❌ | ✅ Trong factory `build_X_registry()` |

**Quy tắc nhớ:**
```
RYUU = mechanism (cách)
Product = policy + content (cái gì + sao)
```

### 5.13 Registration Flow — End-to-End

Khi viết xong YAML + handler, làm thế nào để agent dùng được? Theo thứ tự 4 bước:

```
┌─────────────────────────────────────────────────────────────┐
│  Product viết:                                              │
│    1. prompts/myapp/v1.yaml   (system + user + tool schema) │
│    2. tools.py                (handler implementations)     │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Product wire (main.py / app.py):                           │
│                                                             │
│    # 3. Build ToolRegistry với DI (deps inject vào handler)│
│    tool_registry = build_myapp_registry(db_pool=...)        │
│                                                             │
│    # 4. Build PromptRegistry trỏ vào folder                 │
│    prompt_registry = PromptRegistry(                        │
│        prompts_root=Path("prompts")                         │
│    )                                                        │
│                                                             │
│    # 5. Pass cả 2 vào Agent constructor                     │
│    agent = MyAgent(                                         │
│        agent_id="prod",                                     │
│        prompt_version="v1",       ← chọn version            │
│        tool_registry=tool_registry,                         │
│        prompt_registry=prompt_registry,                     │
│    )                                                        │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Runtime (agent.execute() được gọi):                        │
│                                                             │
│    1. Agent.load(prompt_version)                            │
│       → PromptRegistry trả PromptConfig (cache hit)         │
│                                                             │
│    2. Agent.build_request(prompt_name, **vars)              │
│       → render template + attach tool schema từ YAML        │
│                                                             │
│    3. LLM trả tool_calls                                    │
│                                                             │
│    4. ToolRegistry.run_all(tool_calls, domain=...)          │
│       → dispatch tới handler → trả JSON results             │
│                                                             │
│    5. Loop về step 2 cho tới khi LLM trả final answer       │
└─────────────────────────────────────────────────────────────┘
```

**Code cụ thể — todo_app:**

```python
# main.py
async def main():
    # ── 1. Build tool registry với DI ──
    goals, tasks = load_demo_data()
    tool_registry = build_todo_registry(goals, tasks)

    # ── 2. Build agent ──
    agent = TodoAnalysisAgent(
        agent_id="todo-analyst",
        llm=build_provider(),
        tool_registry=tool_registry,
        prompt_version="v1",          # ← version selection
    )

    # ── 3. Execute ──
    result = await agent.execute(
        Task(payload={"query": "Show priorities", "prompt": "analyze"}),
        ExecutionContext(...),
    )
```

**Bên trong `TodoAnalysisAgent._execute()` (xem `examples/todo_app/agent.py`):**

```python
async def _execute(self, task, context) -> AgentResult:
    # Load YAML version đã chọn
    cfg = _registry.load("todo_app", self.prompt_version)

    # Render với runtime variables
    request = _registry.build_request(
        cfg,
        prompt_name=task.payload["prompt"],   # "analyze" / "priority_breakdown" / ...
        include_tools=bool(self.tool_registry._handlers),
        context=assembled_memory,             # từ ContextAssembler
        query=task.payload["query"],
    )

    # ReAct loop (framework handle tool dispatch)
    response, usage = await self._react_loop(request, max_rounds=3, domain="todo")
    return AgentResult(...)
```

### 5.14 Hot-Swap Version — No Code Change

Khi prompt v2 sẵn sàng test, làm thế nào switch từ v1 → v2 **không sửa code**?

#### Cách 1: Environment Variable (simplest)

```python
# agent.py
import os
prompt_version = os.getenv("TODO_PROMPT_VERSION", "v1")
agent = TodoAnalysisAgent(prompt_version=prompt_version)
```

```bash
# Production
TODO_PROMPT_VERSION=v1 python main.py

# Test v2 trên staging
TODO_PROMPT_VERSION=v2 python main.py

# Rollback nhanh
TODO_PROMPT_VERSION=v1 python main.py    # restart, không deploy lại
```

#### Cách 2: Config File (YAML/TOML)

```yaml
# config/prod.yaml
todo_app:
  prompt_version: v1
  model: gpt-4o-mini

code_analysis:
  prompt_version: v2
  model: gpt-4o
```

```python
# main.py
import yaml
config = yaml.safe_load(open(f"config/{env}.yaml"))
agent = TodoAnalysisAgent(prompt_version=config["todo_app"]["prompt_version"])
```

**Lợi ích:** 1 file config cover nhiều product, dễ diff trong git PR.

#### Cách 3: Per-Request Override (A/B test)

```python
# server.py — handle request
@app.post("/analyze")
async def analyze(req: Request):
    # 10% traffic test v2, 90% giữ v1
    version = "v2" if random() < 0.1 else "v1"

    agent = TodoAnalysisAgent(prompt_version=version)
    return await agent.execute(...)
```

Hoặc qua header:
```python
version = req.headers.get("X-Prompt-Version", "v1")
```

#### Cách 4: Feature Flag Service (production-grade)

```python
from launchdarkly import LDClient    # hoặc Statsig, Unleash

ld = LDClient(...)

async def handle_request(user_id: str, query: str):
    version = ld.variation(
        "todo-prompt-version",
        user={"key": user_id},
        default="v1",
    )
    agent = TodoAnalysisAgent(prompt_version=version)
    return await agent.execute(...)
```

**Lợi ích:** Switch version qua dashboard, không restart server. Có audit trail (ai bật v2 khi nào).

#### So Sánh

| Cách | Setup | Switch không restart? | A/B test? | Audit trail? |
|---|---|---|---|---|
| Env var | 1 dòng | ❌ Restart | ❌ | ❌ |
| Config file | 5 dòng | ❌ Reload | ❌ | Git history |
| Per-request | 3 dòng | ✅ | ✅ | Log custom |
| Feature flag | SDK setup | ✅ | ✅ | ✅ Built-in |

**Khuyến nghị:**
- **Dev/staging:** env var (đơn giản, đủ)
- **Production single-tenant:** config file
- **Production multi-tenant + A/B test:** feature flag service

### 5.15 Cùng Pattern Áp Dụng Cho Tools

Cũng có thể "version" tool set qua YAML:

```yaml
# prompts/todo_app/v2.yaml — tools array khác v1
tools:
  - name: search_tasks_by_tag       # tool MỚI thêm v2
    parameters: { ... }
  - name: get_task_stats             # tool cũ giữ nguyên
    parameters: { ... }
  # v1 có get_blocked_tasks → v2 bỏ vì không hiệu quả
```

**Handler vẫn register tất cả tools trong `tools.py`** — chỉ YAML quyết định LLM thấy tool nào.

```python
# tools.py
def build_todo_registry(goals, tasks):
    registry = ToolRegistry()
    registry.register("get_task_stats", get_task_stats)
    registry.register("get_blocked_tasks", get_blocked_tasks)
    registry.register("search_tasks_by_tag", search_tasks_by_tag)  # mới
    return registry
    # ↑ Register hết. YAML v1 chỉ list 2 tools đầu, LLM chỉ thấy 2.
    #   YAML v2 list tool mới + tool cũ, LLM thấy 2 đúng theo v2.
```

**Lợi ích:**
- Không phải edit `tools.py` khi thêm/bỏ tool — chỉ edit YAML
- Rollback: switch version → tool set tự đổi
- A/B test tool selection per version

### 5.16 Inline vs Registry — When to Use Which

Có 2 mức khai báo prompt + tool. Chọn theo độ phức tạp.

#### 4 Mode Khai Báo Prompt — So Sánh Framework

| Framework | Inline string | File path | YAML reference | System+User riêng |
|---|---|---|---|---|
| **CrewAI** | ✅ | ❌ | ❌ | ❌ (gộp) |
| **Claude Agent SDK** | ✅ | ❌ | ❌ | ✅ |
| **Pydantic AI** | ✅ | ❌ | ❌ | ✅ |
| **OpenAI Agents SDK** | ✅ | ❌ | ❌ | ❌ |
| **LangChain** | ✅ | ✅ | ✅ Hub | ✅ |
| **RYUU đề xuất Phase 10** | ✅ | ✅ | ✅ | ✅ |

#### Mức Lean: Inline (Factory `Agent()`)

Không YAML, không registry. 4 mode khai báo prompt:

```
from pathlib import Path
from ryuu import Agent

# ── Mode 1: shorthand instructions ✅ ──
agent = Agent(model="gpt-4o", instructions="You are a helper.")

# ── Mode 2: tách system + user_template + examples ✅ (Phase 10.1) ──
agent = Agent(
    model="gpt-4o",
    system="You are a translator. Output Vietnamese only.",
    user_template="Translate to VN: {text}",
    examples=[
        {"user": "Hello",  "assistant": "Xin chào"},
        {"user": "Thanks", "assistant": "Cảm ơn"},
    ],
)
result = await agent.run(text="Good morning")
# Template vars qua kwargs. Reserved scope keys (user_id/session_id/domain/correlation_id)
# tự tách khỏi template vars — không bao giờ inject vào prompt.
result = await agent.run(text="Hello", user_id="u-42")   # text → template, user_id → scope

# ── Mode 3: file path (md / txt) ✅ (Phase 10.2) ──
agent = Agent(
    model="gpt-4o",
    system=Path("prompts/personas/analyst.md"),         # đọc file → str
    user_template=Path("prompts/templates/analyze.txt"),
)

# ── Mode 4: YAML registry reference ✅ (Phase 10.2) ──
from ryuu.prompts.registry import PromptRegistry

agent = Agent(
    model="gpt-4o",
    prompt="todo_app:v1:analyze",                       # "project:version:prompt_name"
    prompt_registry=PromptRegistry(prompts_root=Path("./prompts")),
    # Hoặc bỏ prompt_registry → auto-detect ./prompts/
)
# Tools vẫn pass qua Mode A:
agent = Agent(
    model="gpt-4o",
    prompt="todo_app:v1:analyze",
    tools=[get_task_stats, search_tasks],               # Python handlers
)
```

**Validation:** Chỉ 1 mode được set:
```python
# ❌ Lỗi
Agent(instructions="hi", prompt="todo_app:v1:analyze")
# ValueError: Cannot mix `instructions` and `prompt` reference
```

#### Tools — 4 Mode Tương Tự

```python
# Mode A: inline callables — auto schema từ docstring + type hints
def get_weather(city: str) -> dict:
    """Get current weather for a city."""
    return {"city": city, "temp_c": 22}

agent = Agent(model="gpt-4o", tools=[get_weather])

# Mode B: ITool instances (cần state)
agent = Agent(tools=[DBQueryTool(pool=pool), HTTPClientTool(client=...)])

# Mode C: pre-built ToolRegistry (DI + security)
registry = build_todo_registry(deps)
agent = Agent(tool_registry=registry)

# Mode D: YAML reference — tool schema từ YAML v1, handlers từ registry
agent = Agent(
    prompt="todo_app:v1:analyze",       # schema lấy từ YAML
    tool_registry=registry,              # handlers map name → callable
)
```

**Auto-magic phía sau Factory:**
1. `instructions=str` → trở thành `system` message
2. Mỗi callable → wrap thành `_CallableWrapper` (`ITool`)
3. Schema tự sinh từ docstring + type hints
4. Build `ToolRegistry` internal
5. ReAct loop dispatch tự động

**Multi-turn / user template:**

```
# Mặc định: agent.run(query) → query trở thành user message
result = await agent.run("Tokyo weather?")

# Cần user template với variables?
agent = Agent(
    model="gpt-4o",
    instructions="You are a translator.",
    user_template="Translate to {target_lang}: {text}",
)
result = await agent.run(text="Hello", target_lang="Vietnamese")
```

**Few-shot examples inline:**

```python
agent = Agent(
    model="gpt-4o",
    instructions="Extract entities as JSON.",
    examples=[
        {"user": "John went to Paris", "assistant": '{"people": ["John"], "places": ["Paris"]}'},
        {"user": "Meeting at 3pm",      "assistant": '{"people": [], "time": ["3pm"]}'},
    ],
)
```

#### Mức Production: Registry (YAML + ToolRegistry)

Khi inline không đủ:

```python
from ryuu_execution import ToolRegistry
from ryuu.prompts.registry import PromptRegistry

# Tool registry với DI + security
registry = ToolRegistry()
registry.register("db_query", DBQueryTool(db_pool=pool))           # ← state
registry.register("execute_trade", trade_handler,
                  allowed_domains={"trading"})                      # ← security

# Prompt từ YAML versioned
prompts = PromptRegistry(prompts_root=Path("prompts"))

agent = TodoAnalysisAgent(             # class-based, không phải Factory
    agent_id="prod",
    tool_registry=registry,
    prompt_registry=prompts,
    prompt_version="v1",                # ← config switch
)
```

#### Khi Nào Switch Từ Inline → Registry

| Tình huống | Inline đủ | Cần Registry |
|---|---|---|
| < 5 tools, đều stateless | ✅ | — |
| Tool cần db pool, http client, file system | — | ✅ DI |
| Prompt < 50 dòng, ít đổi | ✅ | — |
| Prompt > 200 dòng, A/B test thường xuyên | — | ✅ YAML versioned |
| Multi-tenant — tool/prompt khác per tenant | — | ✅ Registry per tenant |
| Compliance: cần audit "ai sửa prompt khi nào" | — | ✅ YAML + git history |
| Tool nhạy cảm (transfer money, delete data) | — | ✅ `allowed_domains` |
| Prototype, demo, test | ✅ | — |
| Production multi-product (todo + stock + ...) | — | ✅ Shared registry |

#### Pattern Hybrid — Inline Tool + YAML Prompt

Cũng có thể mix: tool inline, prompt từ YAML.

```python
agent = Agent(
    model="gpt-4o",
    prompt_version="v1",                # ← YAML cho prompt (versioned)
    prompt_project="todo_app",
    tools=[get_weather, search_news],   # ← inline cho tool (không cần versioning)
)
```

#### Tách System + User Khi Cần Share

Khi nhiều prompt cùng share 1 persona/rules, có 2 cách:

**Cách 1: `!include` directive trong YAML**

```yaml
# prompts/todo_app/v2.yaml
_shared:
  persona: !include _shared/persona.md

prompts:
  analyze:
    system: "{persona}\n\nFocus: completion rates."
    user: "{query}"
  report:
    system: "{persona}\n\nFocus: structured JSON output."
    user: "{query}"
```

**Cách 2: Tách hẳn folder per use case**

```
prompts/todo_app/v1/
├── _shared/
│   ├── persona.md
│   └── rules.md
├── analyze.yaml
└── report.yaml
```

**Mặc định: gom chung (1 file per version).** Tách khi YAML > 200 dòng hoặc có > 3 use case share persona.

#### Quy Tắc Chọn

```
Prototype / chatbot đơn giản
   → Inline (Factory)

Production single product
   → YAML + ToolRegistry, gom system+user

Production multi-product / multi-tenant / compliance
   → YAML versioned + tách _shared/
```

**Migration path:** Start với inline (Mức Lean), refactor lên registry khi gặp pain point cụ thể — đừng over-engineer từ đầu.

---

## 6. Use Case Matrix

| Use case | Factory | Class | Lý do |
|---|---|---|---|
| Customer support chatbot | ✅ | | Tool calling + instructions đủ |
| RAG (Q&A over docs) | ✅ | | KnowledgeBackbone injectable qua kwarg |
| Code review bot | ✅ | | ReAct strategy + tools |
| Translation service | ✅ | | Stateless, 1 LLM call |
| Stock trading agent | | ✅ | Custom verifier + audit chain + multi-step |
| Multi-agent crew (planner + worker) | | ✅ | AgentPool + custom routing |
| Game AI với state machine | | ✅ | Stateful, custom workflow |
| Coding practice grader | | ✅ | Multi-stage: parse → execute → grade |
| Research assistant | ✅ | | Parallel strategy + fan_out |
| Email triage | ✅ | | Single classification + action |

**Quy tắc**: Nếu logic của bạn = "1 prompt → tool calls → answer" → Factory. Nếu = "intent A→agent X, intent B→agent Y, kết quả gộp lại" → Class.

---

## 7. So sánh với các framework khác

| Framework | API style | Observability | Tool loop | RYUU equivalent |
|---|---|---|---|---|
| **Pydantic AI** | `Agent('openai:gpt-4o', system_prompt=..., tools=[...])` | Logfire (paid) | Auto | Factory |
| **OpenAI Agents SDK** | `Agent(name, instructions, model, tools=[...])` | Traces (paid) | Auto via Runner | Factory |
| **Claude Agent SDK** | `client.messages.create(model, tools=[...])` | None | Manual | Raw OpenAI/Anthropic SDK |
| **CrewAI** | `Agent(role, goal, backstory, tools=[...])` | Custom | Auto | Class (multi-agent) |
| **LangChain** | `Chain(llm, tools, memory).invoke(...)` | LangSmith | Auto, brittle | Class (heavy abstractions) |
| **AutoGen** | `AssistantAgent(name, llm_config, tools=[...])` | None | Auto | Class (multi-agent) |
| **RYUU Factory** (proposed) | `Agent(model, tools=[...], budget_usd=1.0)` | Built-in (OTel + audit) | Auto | — |
| **RYUU Class** | `BaseAgent` subclass | Built-in | Custom (you control) | — |

**Điểm khác biệt RYUU:**
- Observability **built-in & free** (không bị lock vào paid platform)
- Audit hash chain (compliance use cases)
- Có cả 2 modes: factory cho 90%, class cho 10% advanced

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

- **Hôm nay**: Dùng class-based example trong §2 (production-ready)
- **Sau khi factory implement**: Migrate prototype sang `Agent()`
- **Đọc thêm**:
  - [Adapter Guide](adapter-guide.md) — implement provider mới
  - [Runbook](runbook.md) — operational tasks
  - [Architecture v2](../architecture/uaaf-v2-architecture.md) — design rationale

Want factory implemented? Open issue với use case cụ thể.
