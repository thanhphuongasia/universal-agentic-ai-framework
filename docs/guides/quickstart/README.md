# RYUU Quickstart — Index

> Build agent đầu tiên trong < 5 phút. Hiểu khi nào dùng **Factory** (90% use cases) vs **Class-based** (10% advanced) vs các package add-on.
>
> **Vietnamese-first guide** — examples + explanations bằng tiếng Việt, code identifiers giữ tiếng Anh.

---

## 🚀 Cài Đặt (3 phút)

### Local Editable Install (Khuyến nghị cho dev)

Dùng khi bạn đang phát triển cả ryuu + app trên cùng máy. Sửa code framework → app thấy ngay (no reinstall).

```bash
# 1. Tạo venv cho app
cd /path/to/your_app
python3 -m venv .venv
source .venv/bin/activate

# 2. Install ryuu + 13 sub-packages editable (1 lần)
bash /path/to/uaaf-framework/scripts/install-dev.sh

# 3. App giờ dùng được
python -c "from ryuu import Agent; print('OK')"
```

**App's `pyproject.toml`** chỉ cần `dependencies = ["ryuu"]` — KHÔNG cần absolute path. Di chuyển uaaf-framework folder sau này → uninstall + reinstall, không sửa app code.

### Wheel Install (Stable / Deploy)

Sau khi framework stable, build wheel:

```bash
# Trong uaaf-framework
python -m build

# Trong app's venv
pip install /path/to/uaaf-framework/dist/ryuu-0.3.0a11-py3-none-any.whl
```

### PyPI Install (Future, khi published)

```bash
pip install ryuu
# Hoặc cherry-pick:
pip install ryuu-core ryuu-providers ryuu-execution
```

---

## ⚡ Quickstart in 3 Minutes

```python
import anyio
from ryuu import Agent

async def main():
    agent = Agent(
        model="gpt-4o-mini",
        instructions="You are a Python tutor. Keep answers under 80 words.",
    )
    result = await agent.run("What is the difference between list and tuple?")
    print(result.output)

anyio.run(main)
```

Bạn cần `OPENAI_API_KEY` env var. Hết. Đó là 5-line agent với cost tracking + ReAct loop sẵn (NullObject defaults — tự bật qua kwarg khi cần).

---

## Status Legend

✅ shipped — gọi được ngay từ `from ryuu import ...`
🔲 planned — design xong, chưa implement (xem roadmap-phase8.8-to-14.md)

| Feature | Status | Phase | Guide |
|---|---|---|---|
| Async cross-cutting non-blocking (≤ 1k QPS) | ✅ | 8.8 | [03-cross-cutting](03-cross-cutting.md) |
| `BatchSpanProcessor` + `QueuedFileAuditStore` (perf fix) | ✅ | 9.3 | [03-cross-cutting](03-cross-cutting.md) |
| Hook system (10 events + parallel mode) | ✅ | 9.1 + 9.2 | [03-cross-cutting](03-cross-cutting.md) |
| Class-based `BaseAgent` | ✅ | shipped | [02-class-based](02-class-based.md) |
| Factory `Agent()` — 4 prompt modes + 4 tool modes | ✅ | 10 → 10.3 | [01-factory](01-factory.md) |
| `.stream()` (events + token-by-token) | ✅ | 10.4 + 10.6 | [01-factory](01-factory.md#17-streaming) |
| Multi-provider fallback `model=[list]` | ✅ | 10.4 + 10.6 | [01-factory](01-factory.md#14-multi-provider) |
| Multi-agent facades (`Chain`, `FanOut`, `Router`, `Orchestrator`, `Evaluator`) | ✅ | 10.5 | [04-multi-agent](04-multi-agent.md) |
| `HierarchicalRouter` facade (2-stage routing) | ✅ | 14.4 | [04-multi-agent](04-multi-agent.md) |
| `Agent(thinking_mode=True)` — `<thinking>`/`<answer>` parsing | ✅ | 14.1 | [01-factory](01-factory.md) |
| `Agent(n_samples=N, vote=...)` — Best-of-N consensus | ✅ | 14.2 | [01-factory](01-factory.md) |
| `Agent(adaptive_compute=True)` — difficulty → tier dispatch | ✅ | 14.3 | [01-factory](01-factory.md) |
| `Agent(knowledge=RAGBackbone, ...)` — auto RAG context injection | ✅ | 11.x | [01-factory](01-factory.md) |
| `Agent(output_schema=...)` — strict JSON Schema (OpenAI gpt-4o+ / Anthropic) | ✅ | 11.y | [01-factory](01-factory.md) |
| `BatchRunner` — concurrent + OpenAI Batch API | ✅ | 12 + 12.1 | [06-batch](06-batch.md) |
| `PromptOptimizer` — auto-tune via eval | ✅ | 13 | [07-prompt-optimizer](07-prompt-optimizer.md) |
| `ryuu-knowledge-rag` (chunker + vector store + RAGBackbone) | ✅ | 11 | [01-factory](01-factory.md) |
| `ryuu-reasoning` (`RuleVerifier` + optional `Z3Verifier`) | ✅ | 14.7 | [01-factory](01-factory.md) |

---

## TL;DR — Khi nào dùng cái nào?

```
┌─────────────────────────────────────────────────────────┐
│ Chatbot / Tool-calling / RAG / Single domain?           │
│     → Agent()                          [Factory]        │
│                                                         │
│ Multi-agent orchestration / Custom strategy routing /   │
│ Stateful workflow / Custom verifier pipeline?           │
│     → BaseAgent subclass               [Class-based]    │
│                                                         │
│ Compose multiple agents (chain, fan-out, route)?        │
│     → Chain/FanOut/Router/etc.         [Facades]        │
│                                                         │
│ Process N inputs in bulk?                               │
│     → BatchRunner                      [Batch]          │
│                                                         │
│ Auto-tune prompt to maximize eval score?                │
│     → PromptOptimizer                  [Optimizer]      │
└─────────────────────────────────────────────────────────┘
```

**Mặc định**: dùng `Agent()` factory. Chỉ chuyển sang advanced patterns khi factory không cover.

---

## Reading Order

Cho người mới (theo thứ tự):

1. **[01-factory](01-factory.md)** — Lean `Agent()` API. Mode 1 (inline) đủ cho 90% case.
2. **[03-cross-cutting](03-cross-cutting.md)** — Bật/tắt cost tracker, audit, tracer, rate limit, hooks, reasoning.
3. **[04-multi-agent](04-multi-agent.md)** — 5 patterns + Chain/FanOut/Router/Orchestrator/Evaluator facades.
4. **[05-prompt-tool-mgmt](05-prompt-tool-mgmt.md)** — Production: YAML versioning, tool registry với DI, hot-swap.
5. **[02-class-based](02-class-based.md)** — Advanced: BaseAgent subclass.
6. **[06-batch](06-batch.md)** — `BatchRunner` (gather mode + OpenAI Batch API 50% discount).
7. **[07-prompt-optimizer](07-prompt-optimizer.md)** — Auto-tune prompt via eval loop.
8. **[08-framework-comparison](08-framework-comparison.md)** — Pydantic AI / OpenAI Agents / Claude SDK / CrewAI / LangChain.
9. **[09-migration](09-migration.md)** — Day 1 prototype → Day 30 production.

---

## Quick Examples

### Simplest chatbot

```python
import anyio
from ryuu import Agent

async def main():
    agent = Agent(model="gpt-4o-mini", instructions="You are a helpful Python tutor")
    result = await agent.run("What is the difference between list and tuple?")
    print(result.output)

anyio.run(main)
```

### Production with full observability

```python
agent = Agent(
    model="gpt-4o-mini",
    instructions="You are a customer service agent",
    tools=[lookup_customer, check_order],
    max_tokens=512,                       # per-call output cap
    max_iterations=3,                     # ReAct loop cap
    budget_usd=1.00,                       # session cost cap
    rate_limit_rps=10,                     # per-scope rate limit
    audit=True,                            # JSONL hash chain (queued, non-blocking)
    trace=True,                            # OpenTelemetry spans (batch processor)
    verbose=True,                          # stdout debug (CrewAI-style)
    hooks={                                # dynamic lifecycle injection
        "pre_tool":  [pii_scrub],
        "post_tool": [audit_metric],
        "on_error":  [error_logger],
    },
)
result = await agent.run(
    "Check order #123",
    user_id="customer-42",
    session_id="sess-001",
    domain="support",
)
```

### Multi-agent — code review (3 specialist agents)

```python
from ryuu import Agent, FanOut

reviewers = FanOut(
    agents=[
        Agent(name="security", instructions="Audit security vulnerabilities"),
        Agent(name="perf",     instructions="Find performance bottlenecks"),
        Agent(name="style",    instructions="Check code style + conventions"),
    ],
)
results = await reviewers.run(code_snippet)
# → 3 perspectives on same input, run in parallel
```

### Refactor existing app: class-based → Factory

So sánh `examples/todo_app/main.py` (class-based, ~1650 lines tổng) vs
`examples/todo_app/factory_demo.py` (Factory + facades, ~170 lines) — cùng
4 use cases (Priority Breakdown / Per-Goal Effort / Full Analysis / Next Sprint):

```python
# OLD (class-based): 4 custom strategies + IntentAnalyzer + StrategySelector + ToolRegistry wiring
# → ~370 lines strategies.py + 179 lines intent.py + 149 lines agent.py

# NEW (Factory + facades): single file
from ryuu import Agent, Evaluator, FanOut, Router

# Tool Mode C — pre-built registry, DI for goals/tasks
tool_registry = build_todo_registry(goals, tasks)

# 4 agents, 1 system prompt each
report_agent = Agent(model="gpt-4o-mini", instructions="Return ONLY JSON",
                     tool_registry=tool_registry)

# Use case 1: JSON report → Evaluator (auto-refine)
evaluator = Evaluator(generator=report_agent, verifier=_json_check, max_refines=2)
result = await evaluator.run("Priority breakdown as JSON")

# Use case 2: Per-goal fan-out → FanOut
fanout = FanOut(agent=per_goal_agent, items=["g1","g2","g3"],
                template="Analyze {item}")
results = await fanout.run()

# Use case 3+4: Routed by keyword → Router
router = Router(routes={"analyze": analyze_agent, "next_sprint": sprint_agent},
                analyzer=lambda q: "next_sprint" if "sprint" in q else "analyze")
result = await router.run(query)
```

Run cả 2:
```bash
python -m examples.todo_app.main           # original class-based
python -m examples.todo_app.factory_demo   # new Factory + facades
```

### Bulk processing với 50% discount

```python
from ryuu import Agent, BatchRunner

agent = Agent(model="gpt-4o-mini", instructions="Summarize in 1 sentence")
runner = BatchRunner(agent=agent, mode="openai_batch", completion_window="24h")

results = await runner.run([
    {"id": f"doc-{i}", "input": text}
    for i, text in enumerate(corpus_of_10_000)
])
# 50% cost discount, 24h SLA (usually < 1h)
```

### Auto-tune prompt

```python
from ryuu import Agent, EvalCase, PromptOptimizer
from ryuu.prompt_optimizer import llm_variant_generator

cases = [
    EvalCase(input="What is 2+2?", expected="4"),
    EvalCase(input="What is 10*5?", expected="50"),
]
optimizer = PromptOptimizer(
    base_agent=Agent(model="gpt-4o-mini", instructions="You are a math tutor"),
    eval_cases=cases,
    score_fn=lambda out, exp: 1.0 if exp in out else 0.0,
    variant_generator=llm_variant_generator(provider=..., n_variants=3),
    max_rounds=3,
)
best = await optimizer.optimize()
print(f"Best prompt: {best.best_prompt} (score {best.best_score:.2f})")
```

---

## Use Case Matrix

| Use case | Factory | Facades | Class | BatchRunner | PromptOptimizer |
|---|---|---|---|---|---|
| Customer support chatbot | ✅ | | | | |
| RAG (Q&A over docs) | ✅ | | | | |
| Code review (multi-perspective) | | ✅ FanOut | | | |
| Document summarization (1000 docs) | | | | ✅ openai_batch | |
| Codebase analysis | | ✅ Chain + Orchestrator | ✅ | | |
| Stock trading (audit + verifier) | | | ✅ | | |
| Math/logic tutor + improve over time | ✅ | | | | ✅ |
| Game AI với state machine | | | ✅ | | |
| Multi-agent debate | | ✅ Chain với critic | | | |
| Email triage | ✅ | ✅ Router (per category) | | | |
| Translation (1k phrases) | | | | ✅ gather | |
| Translation (1M phrases) | | | | ✅ openai_batch | |

---

## All Top-Level Imports

```python
from ryuu import (
    # Factory (Phase 10 + 14.x kwargs) — single-agent
    Agent, StreamEvent,
    # Multi-agent facades (Phase 10.5 + 14.4)
    Chain, FanOut, Router, HierarchicalRouter, Orchestrator, Evaluator,
    # Batch processing (Phase 12 + 12.1)
    BatchRunner, BatchItem, BatchAPIClient, OpenAIBatchClient,
    # Prompt optimization (Phase 13)
    EvalCase, PromptOptimizer, OptimizationResult,
    # Class-based primitives
    BaseAgent, AgentPool, AgentResult, Task,
    # Intent + observability
    ComplexityLevel, ModelTier, StructuredIntent,
    Cost, Tracer, get_current_correlation_id,
)

# Phase 14.1-14.3 cognitive strategies (Layer A — for advanced/class-based use)
from ryuu_cognitive.strategies import (
    ThinkingStrategy, BestOfNStrategy, AdaptiveStrategy,
    # plus DirectStrategy, ReActStrategy, EvaluatorOptimizerStrategy, ParallelFanoutStrategy
)

# Phase 11 — RAG pipeline (chunker + vector store + IKnowledgeBackbone impl)
from ryuu_knowledge_rag import (
    RecursiveChunker, InMemoryVectorStore, DenseRetriever,
    RAGPipeline, RAGBackbone,
)

# Phase 14.7 — formal verifiers (rule-based + optional Z3 SMT)
from ryuu_reasoning import Rule, RuleVerifier, Z3Verifier   # Z3 optional dep
```

---

## Migration Path

```
Day 1:  Agent() factory                    ← prototype
Day 7:  Agent() + budget_usd + audit       ← production hardening
Day 14: + hooks (PII scrub, approval)      ← compliance / safety
Day 30: BaseAgent subclass (nếu cần)       ← logic phức tạp
Day 60: Multi-agent facades                ← orchestration
```

Detailed: [09-migration](09-migration.md).

---

## Next Steps

- **Hôm nay**: pick từ [Reading Order](#reading-order) — bắt đầu [01-factory](01-factory.md)
- **Production**: [03-cross-cutting](03-cross-cutting.md) bật observability đầy đủ
- **Advanced**: [04-multi-agent](04-multi-agent.md) compose patterns
- **Đọc thêm**:
  - [Adapter Guide](../adapter-guide.md) — implement provider mới
  - [Runbook](../runbook.md) — operational tasks
  - [Architecture v2 rev 3](../../architecture/uaaf-v2-architecture.md) — design rationale
  - [Phase 8.8 Audit Report](../../architecture/phase-8.8-async-audit-report.md) — async non-blocking findings
