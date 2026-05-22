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

# 2. Install ryuu + 33 sub-packages editable (1 lần)
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
pip install ryuu                          # all-in-one (umbrella facade)

# Hoặc cherry-pick chỉ thứ bạn cần (Phase 8.x splits):
pip install ryuu-providers-openai          # only OpenAI adapter + core
pip install ryuu-storage-sqlite            # only SQLite KV/Collection
pip install ryuu-messaging-telegram        # only Telegram channel
pip install ryuu-observability-core        # only in-process cost/audit (no OTel SDK)
pip install ryuu-eval-core                 # eval framework without default scorers
pip install ryuu-hooks                     # lifecycle hooks only
pip install ryuu-prompts                   # versioned YAML prompt registry
```

> Phase 8.x đã tách framework thành **33 packages** theo Clean Architecture:
> top-level = Domain + Use Case, `infrastructure/` = adapters tới external systems.
> Mỗi sub-package install độc lập (pulls in dependencies theo demand).

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

## 🎯 RecallPipeline — khi nào dùng, khi nào skip

`ryuu_cognitive.recall.RecallPipeline` orchestrate preprocessing trước LLM (intent filter → expansion → decomposition → multi-query retrieval → RRF fusion → token budget). Nhưng **không phải mọi use case đều cần.**

### Decision tree

```
LLM có chạy ReAct loop với memory/recall tools không?
│
├── YES (Agent factory, tool_use enabled)
│   │
│   └─> SKIP RecallPipeline.
│       LLM tự decompose compound queries via parallel tool_use.
│       LLM tự retry với paraphrase khi miss.
│       Chỉ cần warm-start (top-N recent observations pre-injected).
│
└── NO (single-shot LLM call, no tools, no iteration)
    │
    └─> USE RecallPipeline.
        Preprocessing là cách DUY NHẤT để cải thiện recall quality.
```

### Lý do

ReAct pattern (`Agent()` factory mặc định) — LLM iterate:
```
User: "list todos and create flashcards"
   ↓
LLM Thought: "2 việc — gọi recall 2 lần"
LLM Action: recall("todos")          ← decomposition tự nhiên
   ↓
LLM Action: recall("notes for flashcards")
   ↓
LLM synthesizes → answer
```

Pre-LLM decomposition lúc này = redundant. Cùng kết quả, thêm chi phí.

### Khi nào VẪN cần RecallPipeline?

| Use case | Lý do |
|----------|-------|
| **RAG-only** (single LLM call, no tools, no iteration) | Không có cơ hội iterate → preprocessing là cách duy nhất |
| **`Agent(max_iterations=1)`** (cost cap) | Bị khoá ở 1 turn → cần pre-fetch context đầy đủ |
| **Search-as-service** (expose retrieval API, không LLM) | Pipeline = the product itself |
| **Batch processing** (offline scoring, không model conv) | Không có ReAct loop |
| **Streaming completion** không có function calling | Same — không tool_use → preprocess |

### Code: 2 paradigms

**Paradigm 1 — ReAct agent (mặc định cho hầu hết products):**

```python
# RyuuHandler / TodoHandler / SuperBot — KHÔNG cần RecallPipeline
from ryuu_knowledge_memory import MemoryBackbone, MemoryToolset
from ryuu import Agent

toolset = MemoryToolset(backbone=memory_backbone)
agent = Agent(
    model="gpt-4o-mini",
    tools=toolset.tools,    # recall, remember, list_memories
    max_iterations=4,        # ReAct loop iterates
)

async def handle(msg, session):
    # Warm-start: top-3 recent observations (cheap, no LLM call)
    recent = await memory_backbone.query("", scope_key=scope, top_k=3)
    warm = "What I know:\n" + "\n".join(f"- {r}" for r in recent.results)
    
    async with toolset.bind(scope_key=scope):
        result = await agent.run(f"{warm}\n\nUser: {msg.text}")
    # Agent's ReAct loop calls recall() N times as needed
```

**Paradigm 2 — RAG / non-iterating (cần preprocessing):**

```python
# Search service / batch processor — DÙNG RecallPipeline
from ryuu_cognitive.recall import RecallPipelineBuilder
from ryuu_cognitive.context import LLMQueryExpander
from ryuu_intent import LLMIntentAnalyzer

pipeline = RecallPipelineBuilder.full(
    backbone=memory_backbone,
    analyzer=LLMIntentAnalyzer(provider=...),
    expander=LLMQueryExpander(provider=..., registry=...),
    decomposer=LLMQueryDecomposer(provider=..., registry=...),
)

# Each request: full preprocessing → enriched context → 1 LLM call
async def handle_query(query):
    result = await pipeline.recall(query=query, scope_key="...")
    # Use result.text in single LLM call (no agent, no iteration)
    return await llm.complete(f"Context:\n{result.text}\n\nQuery: {query}")
```

### Tóm lại

```
✅ Agent + tools + ReAct        → skip RecallPipeline, warm-start đủ
✅ Single LLM call, RAG          → RecallPipeline.full()
✅ Search API (no LLM)            → RecallPipeline custom stages
✅ Batch / offline scoring        → RecallPipeline + sequential
```

---

## 🍳 Cookbook — Patterns mới (Phase 8.x + 9.x primitives)

### Override prompts WITHOUT redeploying code (Phase 8.9.E)

Mọi prompt LLM đều ở YAML, load qua `PromptRegistry`. Edit YAML → restart process → prompt mới active.

```python
from pathlib import Path
from ryuu_prompts import PromptRegistry, make_framework_registry

# Layered overlay: user dir shadows framework defaults
registry = make_framework_registry(
    user_overrides_root=Path("~/.ryuu/prompts").expanduser(),
)

# Then anywhere a primitive needs prompts:
from ryuu_cognitive.context import LLMCompactor
from ryuu_providers_openai import OpenAIProvider

compactor = LLMCompactor(
    provider=OpenAIProvider(api_key=...),
    registry=registry,
    # Reads from: ~/.ryuu/prompts/compaction/v1.yaml (user shadow)
    #         OR: <pkg>/ryuu_cognitive/prompts/compaction/v1.yaml (default)
)
```

To override compaction prompt for your app:
```bash
mkdir -p ~/.ryuu/prompts/compaction
cp <pkg>/ryuu_cognitive/prompts/compaction/v1.yaml ~/.ryuu/prompts/compaction/v1.yaml
# edit it → restart bot → new prompt active
```

See [faq_memory_storage.md](../../faq/faq_memory_storage.md) — SQLite vs JSONL.

### Recall — semantic memory with persistence (Phase 8.9.E)

```python
from ryuu_knowledge_memory import MemoryBackbone
from ryuu_knowledge_memory.working import WorkingMemoryStore
from ryuu_knowledge_memory.episodic import EpisodicMemoryStore
from ryuu_storage_jsonl import JsonlCollectionStore   # append-only, OpenClaw-style

bb = MemoryBackbone(layers=[
    WorkingMemoryStore(
        collection=JsonlCollectionStore(root_dir="~/.ryuu/memory", table="working"),
    ),
    EpisodicMemoryStore(
        collection=JsonlCollectionStore(root_dir="~/.ryuu/memory", table="episodic"),
    ),
])

# Write observation
await bb.write("User prefers Vietnamese cuisine", scope_key="owner")

# Retrieve semantically (keyword overlap; vector when knowledge-rag wired)
result = await bb.query("food preferences", scope_key="owner", top_k=3)

# Or token-budget aware context for LLM prompt
ctx = await bb.assemble_context(
    query="What does the user like to eat?",
    scope_key="owner",
    budget_tokens=2000,
)
prompt = f"{ctx.text}\n\nUser asks: ..."
```

### Context compaction — shrink long conversations

```python
from ryuu_cognitive.context import LLMCompactor, CompactionTurn

compactor = LLMCompactor(
    provider=openai_provider, registry=registry,
    threshold_tokens=8000, keep_recent_turns=5,
)

# Inside handler:
history = [CompactionTurn(role=t.role, text=t.text) for t in session.history]
if await compactor.needs_compaction(history, approx_tokens=total_tokens):
    history = await compactor.compact(history)   # 50 turns → 1 summary + 5 recent
```

### Query expansion + decomposition

```python
from ryuu_cognitive.context import (
    LLMQueryExpander, SynonymExpander,
    LLMQueryDecomposer, PatternQueryDecomposer,
)

# LLM-based (paid, high-quality)
expander = LLMQueryExpander(provider=p, registry=r, num_variants=3)
queries = await expander.expand("tell me about my Tokyo trip")
# → ["tell me about my Tokyo trip", "Japan visit", "trip to Tokyo", "visiting Japan"]

# Non-LLM fallback (free, predictable)
syn = SynonymExpander(num_variants=3)
queries = await syn.expand("buy a task")
# → ["buy a task", "purchase a task", "buy a todo", ...]

# Decompose complex query into sub-tasks
decomposer = LLMQueryDecomposer(provider=p, registry=r, max_subqueries=5)
subs = await decomposer.decompose(
    "summarize my unfinished todos and create Anki cards from notes"
)
# → [SubQuery("list+summarize todos", intent="list"),
#    SubQuery("create Anki cards", intent="create")]
```

### Single-tenant SuperBot pattern (private assistant — only YOU)

```python
from ryuu_messaging_core import (
    ChannelOrchestrator, ConversationManager,
    SingleTenantResolver, KVSessionStore,
)
from ryuu_messaging_telegram import TelegramAdapter
from ryuu_storage_sqlite import SqliteKVStore

cm = ConversationManager(
    session_store=KVSessionStore(kv=SqliteKVStore(db_path="~/.ryuu/store.db", table="sessions")),
    scope_resolver=SingleTenantResolver(scope_key="owner"),  # everyone → same scope
)

tg = TelegramAdapter(
    bot_token=os.environ["RYUU_BOT_TOKEN"],
    allowed_senders={os.environ["OWNER_TELEGRAM_ID"]},   # reject non-owner DMs
    # ... callbacks ...
)
```

### Multi-tenant product pattern (Todo / Flash / Stock — many users)

```python
from ryuu_messaging_core import DefaultScopeResolver, KVSessionStore

cm = ConversationManager(
    session_store=KVSessionStore(kv=SqliteKVStore(db_path=..., table="sessions")),
    scope_resolver=DefaultScopeResolver(),   # → f"{channel}:{sender_id}" per-user scope
)

tg = TelegramAdapter(
    bot_token=os.environ["TODO_BOT_TOKEN"],
    # No allowlist — ANY Telegram user can DM
    # Each user gets isolated scope via DefaultScopeResolver
)
```

→ Compare: [single_tenant_assistant.md] vs [multi_tenant_product.md] cookbooks (planned).

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

# Phase 8.x — Standalone packages (direct imports, no umbrella overhead)
from ryuu_providers_core import ILLMProvider, CompletionRequest, Message
from ryuu_providers_openai import OpenAIProvider
from ryuu_providers_anthropic import AnthropicProvider

from ryuu_observability_core import CostTracker, AuditLogger, RateLimiter
from ryuu_observability_otel import Tracer, setup_tracing      # OTel SDK adapter

from ryuu_prompts import PromptRegistry, make_framework_registry
from ryuu_intent import LLMIntentAnalyzer, normalize_difficulty, Difficulty
from ryuu_hooks import HookEvent, HookRegistry

# Phase 8.15 — eval split
from ryuu_eval_core import EvalRunner, EvalCase, Scorer, EvalTarget, FixtureLoader
from ryuu_eval_scorers import ExactMatch, Constraint, Threshold, LLMJudge

# Phase 8.9 — storage primitives
from ryuu_storage_core import IKVStore, ICollectionStore
from ryuu_storage_sqlite import SqliteKVStore, SqliteCollectionStore
from ryuu_storage_jsonl import JsonlCollectionStore
from ryuu_storage_memory import InMemoryKVStore                # tests / dev

# Phase 8.8 — messaging primitives
from ryuu_messaging_core import (
    ChannelOrchestrator, ConversationManager,
    DefaultScopeResolver, SingleTenantResolver,                # multi vs single tenant
    KVSessionStore, IncomingMessage, OutgoingMessage,
    IChannelHandler, IChannelAdapter,
)
from ryuu_messaging_cli import CLIAdapter
from ryuu_messaging_telegram import TelegramAdapter

# Phase 8.x — context preprocessing (LLM-driven + non-LLM fallbacks)
from ryuu_cognitive.context import (
    LLMCompactor, HierarchicalCompactor,                       # shrink history
    LLMQueryExpander, SynonymExpander,                          # paraphrase queries
    LLMQueryDecomposer, PatternQueryDecomposer,                 # split complex queries
    CompactionTurn, SubQuery,
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
  - [faq_memory_storage.md](../../faq/faq_memory_storage.md) — SQLite vs JSONL decision matrix
  - [faq_general.md](../../faq/faq_general.md) — general FAQ
  - [Architecture v2 rev 3](../../architecture/uaaf-v2-architecture.md) — design rationale
  - [Phase 8.8 Audit Report](../../architecture/phase-8.8-async-audit-report.md) — async non-blocking findings
