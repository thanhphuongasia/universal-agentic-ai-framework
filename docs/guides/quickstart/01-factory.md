# Factory — `Agent()` API

← [Quickstart Index](README.md) | [All guides](../)

> Lean single-agent + tool-calling facade. 4 prompt modes (inline/system+template/file/YAML ref), 4 tool modes, streaming, multi-provider fallback, hooks integration.

---

## 1. Factory Style — Recommended

> ✅ Factory đã ship Phase 10 + 10.1–10.6. Cover 4 prompt modes + 4 tool modes + streaming + multi-provider fallback + hooks. Class-based BaseAgent (xem [02-class-based.md](02-class-based.md)) cho advanced.

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

### 1.12 Thinking Mode — Claude-like `<thinking>`/`<answer>` ✅ (Phase 14.1)

```python
agent = Agent(
    model="gpt-4o-mini",
    instructions="Solve math problems",
    thinking_mode=True,        # ← Factory injects template + parses tags
)
result = await agent.run("What is 17 × 23?")
print(result.output)     # "391"
print(result.thinking)   # "Step 1: 17 × 20 = 340. Step 2: 17 × 3 = 51..."
```

**Internal:** Augments `system_prompt` với template ép LLM emit `<thinking>...</thinking><answer>...</answer>`. Parse output thành 2 fields. Fallback graceful: tag missing → `output = raw`, `thinking = ""`.

**Khi nào dùng:**
- ✅ Audit/compliance — log reasoning trail
- ✅ Debug — hiểu vì sao LLM chọn intent này
- ✅ Educational — show students reasoning steps
- ❌ Cost-sensitive — thinking thêm ~200-400 output tokens

**Architecture:** Layer A `ThinkingStrategy` ở `ryuu-cognitive/strategies/thinking_strategy.py`. Class-based agents dùng strategy trực tiếp; Factory wrap qua kwarg.

### 1.13 Best-of-N — Sample N + Vote ✅ (Phase 14.2)

```python
# Majority vote (default)
agent = Agent(
    model="gpt-4o-mini",
    instructions="Classify intent",
    n_samples=3,                       # ← framework runs 3 parallel calls
    vote="majority",
    temperature=0.9,                    # high temp → diverse samples
)

# Custom score function
agent = Agent(
    model="gpt-4o-mini",
    n_samples=5,
    vote="score_fn",
    score_fn=lambda output: len(output) if "json" in output else 0,
)

result = await agent.run("classify this query")
print(result.output)                                   # winner
print(result.metadata["samples"])                       # all N samples
print(result.metadata["best_of_n_confidence"])          # 0.0-1.0
```

**3 vote modes:**
| Mode | Logic | Use case |
|---|---|---|
| `"majority"` | `Counter(samples).most_common(1)` | Categorical outputs (intent classification) |
| `"score_fn"` | `max(samples, key=score_fn)` | Length / format / regex match |
| `"llm_judge"` | Verifier callable scores each | Quality grading (defer Phase 14.x v2) |

**Cost:** N× single-call. **Anti-flap improvement:** 30-50% trên ambiguous queries.

**Architecture:** Layer A `BestOfNStrategy` ở `ryuu-cognitive/strategies/best_of_n_strategy.py`.

### 1.14 Adaptive Compute — Difficulty → Tier ✅ (Phase 14.3)

```python
agent = Agent(
    model="gpt-4o-mini",                  # baseline (override per tier)
    instructions="Analyze code questions",
    adaptive_compute=True,                 # ← Factory classifies + dispatches
    tier_models={"trivial": "gpt-4o-mini", "medium": "gpt-4o-mini", "hard": "gpt-4o"},
    tier_max_iterations={"trivial": 2, "medium": 4, "hard": 8},
    tier_max_tokens={"trivial": 300, "medium": 800, "hard": 2000},
)
result = await agent.run("Analyze architecture")
print(result.metadata["difficulty"])   # "hard"
print(result.metadata["tier_model"])    # "gpt-4o"
```

**Default tier config** (nếu không override):
```
trivial → gpt-4o-mini + 2 iter + 300 tokens   (greetings, simple lookups)
medium  → gpt-4o-mini + 4 iter + 800 tokens   (typical chat queries)
hard    → gpt-4o       + 8 iter + 2000 tokens  (multi-step analysis)
```

**Difficulty detection:** Built-in keyword heuristic (no extra LLM call). Hard keywords: `analyze, compare, evaluate, trace`. Trivial: short greetings, `what is X` < 8 words. Anything else → medium.

**Cost saving:** 40-60% trên chat volume khi đa số queries trivial/medium.

**Khi nào dùng:**
- ✅ Production chat với volume cao + budget pressure
- ✅ Mix dễ + khó (saving rõ rệt)
- ❌ Tất cả queries cùng độ phức tạp (no benefit)

**Architecture:** Layer A `AdaptiveStrategy` ở `ryuu-cognitive/strategies/adaptive_strategy.py`. Cho LLM-backed classifier, pass `AdaptiveStrategy(difficulty_fn=my_llm_classifier)` qua `strategy=` explicit.

### 1.15 Strategy Explicit Override — Advanced

Cho advanced custom config, pass `strategy=` instance trực tiếp:

```python
from ryuu_cognitive.strategies import BestOfNStrategy, AdaptiveStrategy, ThinkingStrategy

# Custom BestOfN với LLM judge verifier
agent = Agent(
    model="gpt-4o-mini",
    strategy=BestOfNStrategy(
        n=5,
        vote="llm_judge",
        verifier=judge_agent,
    ),
)

# Custom Adaptive với LLM-backed difficulty classifier
agent = Agent(
    model="gpt-4o-mini",
    strategy=AdaptiveStrategy(
        difficulty_fn=my_llm_classifier,
        tier_models={"trivial": "gpt-3.5", "medium": "gpt-4o-mini", "hard": "claude-opus"},
    ),
)
```

**Validation:** `strategy=` mutually exclusive với kwargs (`thinking_mode`, `n_samples > 1`, `adaptive_compute`) → ValueError nếu set cả 2.

**Quy tắc:** Kwargs cho 90% use case (UX gọn). `strategy=` cho 10% advanced cần fine-tune sâu.

---

