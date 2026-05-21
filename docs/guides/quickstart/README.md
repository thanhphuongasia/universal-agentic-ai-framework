# RYUU Quickstart — Index

> Build agent đầu tiên trong < 5 phút. Hiểu khi nào dùng **Factory** (90% use cases) vs **Class-based** (10% advanced) vs các package add-on.
>
> **Vietnamese-first guide** — examples + explanations bằng tiếng Việt, code identifiers giữ tiếng Anh.

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
| Multi-agent facades (`Chain`, `FanOut`, ...) | ✅ | 10.5 | [04-multi-agent](04-multi-agent.md) |
| `BatchRunner` — concurrent + OpenAI Batch API | ✅ | 12 + 12.1 | [06-batch](06-batch.md) |
| `PromptOptimizer` — auto-tune via eval | ✅ | 13 | [07-prompt-optimizer](07-prompt-optimizer.md) |
| `ryuu-knowledge-rag` | 🔲 | 11 | (planned) |
| `ryuu-reasoning` (Z3/Prolog) | 🔲 | 14 | (planned) |

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
    # Factory (Phase 10) — single-agent
    Agent, StreamEvent,
    # Multi-agent facades (Phase 10.5)
    Chain, FanOut, Router, Orchestrator, Evaluator,
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
