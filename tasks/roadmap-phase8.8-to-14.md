# RYUU Roadmap: Phase 8.8 → 14

> **Date drafted**: 2026-05-21
> **Last updated**: 2026-05-21 (Option A chosen — Factory trước Hooks)
> **Context**: Tổng hợp sau khi review (1) async audit chưa verify, (2) hook system chưa có, (3) factory `Agent()` chưa implement, (4) Bedrock feature gap (RAG/batch/prompt-opt/reasoning).
> **Status**: Option A locked. Phase 8.8 + 10 MVP first.

## 🎯 Decision: Option A — DX-First

Đã chọn **Option A** (Factory trước Hooks) thay vì Option B (Hooks trước).

**Lý do:**
1. Factory MVP nhỏ (1 tuần) — quick visible win
2. Adding `hooks=` kwarg vào Factory v2 là non-breaking
3. User mới adopt cần "viết agent thế nào", không phải "inject middleware thế nào"
4. Class-based vẫn cover production case cần hooks

**Thứ tự thực thi:**

```
Tuần 1   │ Phase 8.8 Audit              ← foundation, không skip
Tuần 2   │ Phase 10 Factory MVP         ← DX win nhanh (Mode 1 inline only)
Tuần 3-4 │ Phase 9 Hooks                ← production unlock
Tuần 5   │ Phase 10.x Factory v2        ← thêm Modes 2-4 + hooks= param
Tuần 6-7 │ Phase 10.5 Multi-agent       ← Chain/FanOut/Router/Orchestrator/Evaluator
```

**Detailed plan:** `tasks/plan-phase10-factory.md` + `tasks/todo-phase10-factory.md`

---

## 1. Vấn Đề Tồn Đọng — Phân Loại

### A. Kiến trúc cần đổi (P0 — block các feature khác)

| # | Vấn đề | Mức độ | Block gì? |
|---|---|---|---|
| 1 | **Hook system chưa có** | Critical | Factory API, dynamic injection, PII filter, approval workflow |
| 2 | **Audit/Cost có thật sự async không?** | Critical | Performance ở high QPS, không thể kết luận production-ready |
| 3 | **Factory `Agent()` chưa implement** | High | 90% use case phải dùng class-based (verbose), khó adopt |
| 4 | **Tool registry tách rời khỏi hooks** | Medium | Tool calling không inject được pre/post logic |

### B. Feature mới (P1 — không block, nhưng cần để cover Bedrock)

| # | Vấn đề | Mức độ | Lý do |
|---|---|---|---|
| 5 | **`ryuu-knowledge-rag`** thiếu | High | RAG là use case #1 production |
| 6 | **`ryuu-batch`** thiếu | Medium | Bedrock có, cần cho dataset processing |
| 7 | **`ryuu-prompt-optimizer`** thiếu | Medium | Auto-tune prompt qua eval loop |
| 8 | **`ryuu-reasoning`** thiếu | Low | High-stakes domain only (medical/finance), không phải majority |

### C. Polish (P2 — nice to have)

| # | Vấn đề | Mức độ |
|---|---|---|
| 9 | Streaming events chưa unified (mỗi adapter custom) | Medium |
| 10 | Visual flow editor (giống Bedrock Flows) | Low |
| 11 | Fine-tuning helpers (LoRA, distillation) | Low |

---

## 2. Async Audit — Cần Verify Trước

**Câu hỏi gốc**: *"đang dùng async để tránh block chưa?"*

Audit thực tế 4 cross-cutting concerns:

```
ryuu-observability/
├── cost.py        ← async hay sync? track() có await disk write?
├── audit.py       ← JSONL append có block event loop?
├── tracer.py      ← OpenTelemetry export có sync?
└── rate_limit.py  ← Token bucket có lock contention?
```

**Phải làm:** Audit code thực tế, không tin docstring. Test với 1000 concurrent requests, đo p99 latency.

**Nếu phát hiện blocking** → fix bằng:
- `aiofiles` thay open()/write()
- Background queue (asyncio.Queue) + worker task
- OTLP exporter async mode

---

## 3. Roadmap Đề Xuất (Theo Thứ Tự Ưu Tiên)

### **Phase 8.8: Async Audit & Verification** (1 tuần) ← LÀM TRƯỚC

**Tại sao đầu tiên?** Không thể build trên nền tảng không biết có async hay không.

**Việc cần làm:**
1. Đọc `cost.py`, `audit.py`, `tracer.py`, `rate_limit.py`
2. Viết stress test (1000 concurrent agents)
3. Đo blocking time
4. Fix nếu cần (aiofiles, background queue)
5. Document async guarantees vào README

**Deliverable:** "Audit/Cost guaranteed non-blocking dưới 10k QPS"

---

### **Phase 9: Hook System Core** (2 tuần)

**Tại sao kế tiếp?** Block Factory + tất cả dynamic injection.

**File cần tạo:**
```
packages/ryuu-core/src/ryuu_core/
├── hooks.py           ← HookEvent enum, HookContext types
├── hook_registry.py   ← register, fire, async coordination
└── protocols.py       ← IHookHandler (thêm vào file hiện có)

packages/ryuu-execution/src/ryuu_execution/
└── agent.py           ← integrate hooks: pre_execute, post_execute, on_error
```

**Phạm vi Phase 9.1 (MVP):**
- 6 events: pre_execute, post_execute, pre_llm, post_llm, on_error, on_complete
- Dict-based registration
- Sequential mode only
- Tests: 12 test cases (1 per event + 6 integration)

**Phase 9.2 (extend):**
- Thêm pre_tool, post_tool, on_budget_exceeded, on_rate_limited
- Decorator + class-based registration
- Parallel fire mode (cho metrics, không block path)

**Reference:** `docs/guides/hooks.md` (đã viết spec đầy đủ).

---

### **Phase 10: Agent() Factory** (1 tuần)

**Tại sao sau hooks?** Factory expose `hooks=` param, cần hook system sẵn.

**File cần tạo:**
```
packages/ryuu/src/ryuu/
├── __init__.py        ← re-export Agent
└── factory.py         ← Agent dataclass + build logic
```

**API target:**
```python
@dataclass
class Agent:
    model: str | list[str]
    instructions: str = ""
    tools: list[Callable] = field(default_factory=list)
    budget_usd: float | None = None
    rate_limit_rps: float | None = None
    audit: bool = False
    trace: bool = False
    hooks: dict[str, list[Callable]] = field(default_factory=dict)

    async def run(self, message: str, **scope) -> AgentResult: ...
    async def stream(self, message: str, **scope) -> AsyncIterator[Event]: ...
```

**Build logic:**
1. Parse `model` string → provider class (openai:/anthropic: prefix)
2. Build tools schema từ docstring + type hints (`inspect`)
3. Wire cross-cutting (None → NullObject, set → real instance)
4. Register hooks vào HookRegistry
5. Return wrapper around BaseAgent + tool loop

**Deliverable:** Quickstart.md §1 examples chạy được thật.

---

### **Phase 11: `ryuu-knowledge-rag`** (2 tuần)

**Tại sao sau Factory?** RAG inject vào Agent qua `knowledge=` param.

**File cần tạo:**
```
packages/ryuu-knowledge-rag/
├── chunker.py         ← TextChunker (token-aware splitting)
├── retriever.py       ← VectorRetriever protocol + adapters (chroma, qdrant, pgvector)
├── reranker.py        ← Optional reranker (cross-encoder)
├── pipeline.py        ← RAGPipeline (chunk → embed → retrieve → rerank)
└── backbones.py       ← RAGBackbone (impl IKnowledgeBackbone)
```

**Tích hợp:**
```python
from ryuu import Agent
from ryuu_knowledge_rag import RAGBackbone

backbone = RAGBackbone(documents=["docs/*.md"], vector_db="chroma")
agent = Agent(model="gpt-4o", knowledge=backbone, tools=[...])
```

---

### **Phase 12: `ryuu-batch`** (1 tuần)

**Tại sao?** Bedrock có, OpenAI/Anthropic đều support batch API → tiết kiệm 50% cost.

```python
from ryuu_batch import BatchRunner

runner = BatchRunner(agent=my_agent, provider="openai")
results = await runner.run_batch([
    {"task_id": "t1", "input": "..."},
    {"task_id": "t2", "input": "..."},
    # 10,000 tasks
])
# Auto-uses OpenAI Batch API (50% discount, 24h SLA)
```

---

### **Phase 13: `ryuu-prompt-optimizer`** (2 tuần)

**Cần `ryuu-eval` sẵn (đã có).** Loop tự động:

```
1. Eval current prompt → score
2. Generate variants (paraphrase, restructure, add examples)
3. Eval variants → pick best
4. Repeat N rounds
```

Tham khảo: DSPy, OpenAI Prompt Optimizer beta.

---

### **Phase 14.1-14.6: Claude-like Thinking Patterns** (~17h)

> **Trigger:** Code analysis team feedback — patterns universal (thinking, adaptive
> compute, best-of-N, hierarchical classify) phải ở framework, không phải product code.
>
> **Architecture decision (2026-05-21)**: 2-layer placement:
> - **Layer A (mechanism)** — `ryuu-cognitive/strategies/` cho cognitive patterns
> - **Layer B (ergonomic)** — `ryuu/factory.py` kwargs + `ryuu/facades.py` cho routing
> - Factory expose **Option A**: kwargs convenience (90% use) + `strategy=` explicit (advanced)

**Sub-phases:**

| Phase | Layer | Add | Effort |
|---|---|---|---|
| **14.1** | Cognitive | `ThinkingStrategy` + Factory `thinking_mode=True` wire | 3h |
| **14.2** | Cognitive | `BestOfNStrategy` + Factory `n_samples=N, vote=...` wire | 4h |
| **14.3** | Cognitive | `AdaptiveStrategy` + Factory `adaptive_compute=True` wire | 4h |
| **14.4** | Facade (routing) | `HierarchicalRouter` facade trong `ryuu/facades.py` | 3h |
| **14.5** | Docs | Update migration guide §16, architecture §7 | 1h |
| **14.6** | Demo | Update `intent_patterns_demo.py` before/after | 2h |

**File cần tạo/sửa:**
```
packages/ryuu-cognitive/src/ryuu_cognitive/strategies/
├── thinking_strategy.py          ← NEW (Phase 14.1) — wraps base strategy with <thinking>/<answer>
├── best_of_n_strategy.py          ← NEW (Phase 14.2) — sample N + vote (majority/llm_judge/score_fn)
└── adaptive_strategy.py           ← NEW (Phase 14.3) — difficulty → tier model selection

ryuu/factory.py                    ← MODIFY: thinking_mode/n_samples/vote/adaptive_compute/tier_* kwargs
                                            + strategy= explicit param (advanced)
ryuu/facades.py                    ← MODIFY: add HierarchicalRouter (Phase 14.4)
ryuu/_thinking_parser.py            ← NEW (Phase 14.1) — parse <thinking> + <answer> tags helper
ryuu/_difficulty_classifier.py      ← NEW (Phase 14.3) — cheap default classifier helper

tests/unit/cognitive_pkg/
├── test_thinking_strategy.py       ← NEW (~6 tests Phase 14.1)
├── test_best_of_n_strategy.py       ← NEW (~6 tests Phase 14.2)
└── test_adaptive_strategy.py        ← NEW (~5 tests Phase 14.3)

tests/unit/ryuu/
├── test_factory_thinking.py         ← NEW (~3 tests — Factory wire to ThinkingStrategy)
├── test_factory_best_of_n.py        ← NEW (~3 tests — Factory wire to BestOfNStrategy)
├── test_factory_adaptive.py         ← NEW (~3 tests — Factory wire to AdaptiveStrategy)
└── test_hierarchical_router.py      ← NEW (~5 tests Phase 14.4)
```

**Detailed plan**: `tasks/plan-phase14-thinking-patterns.md`

**Rationale:**
- Strategies ở `ryuu-cognitive` → class-based BaseAgent dùng được, không bị lock vào Factory
- Factory kwargs cho ergonomic UX, `strategy=` cho advanced custom
- HierarchicalRouter là routing, không phải cognitive — đúng vị trí ở `ryuu/facades.py`
- LOC saving: ~200 lines self-impl/pattern × 4 patterns × N apps → maintain 1 lần ở framework

---

### **Phase 14.7: `ryuu-reasoning`** (3 tuần)

**Cuối cùng vì:**
- Niche use case (finance/medical only)
- Phụ thuộc Z3/Prolog (heavy deps, không nên trong core path)
- Đã có 3 verifier tier sẵn (Schema/LLMJudge/GroundTruth) cover 80%

**File cần tạo:**
```
packages/ryuu-reasoning/
├── z3_backend.py        ← Constraint checking (numerical, optimization)
├── prolog_backend.py    ← Rule querying (business rules, logical chains)
├── soufflé_backend.py   ← Pattern analysis (fraud, anomaly detection)
└── formal_verifier.py   ← IVerifier impl, orchestrates all backends
```

**Use case examples:**
- **Z3**: Trading bot — `loan_amount ≤ 0.3 × income AND amount ≤ 100000`
- **Prolog**: Medical advisor — `can_prescribe(Drug, Patient) :- no_allergy(...), treats(...)`
- **Soufflé**: Fraud detection — `3+ approvals > $40k in 1h → suspicious`

**Tích hợp vào VerifierPipeline:**
```
SchemaVerifier → LLMJudgeVerifier → GroundTruthVerifier → FormalVerifier
   (syntax)       (semantic)         (accuracy)            (proof — NEW)
```

---

## 4. Lịch Trình Tổng

```
Week 1     │ Phase 8.8 │ Async audit + verify
Week 2-3   │ Phase 9   │ Hook system core
Week 4     │ Phase 10  │ Agent() factory
Week 5-6   │ Phase 11  │ ryuu-knowledge-rag
Week 7     │ Phase 12  │ ryuu-batch
Week 8-9   │ Phase 13  │ ryuu-prompt-optimizer
Week 10    │ Phase 14.1-14.6 │ Claude-like thinking patterns (4 facades + docs)
Week 11-13 │ Phase 14.7│ ryuu-reasoning
```

**Total: ~12 tuần (3 tháng)** để có framework feature-parity với Bedrock + production-ready.

---

## 5. Cây Quyết Định: Làm Gì Trước?

```
┌──────────────────────────────────────────────────────┐
│ Bạn có user thật đang chạy production không?         │
└──────────────────────────────────────────────────────┘
         │                              │
        YES                            NO
         │                              │
         ▼                              ▼
   Phase 8.8 NGAY                Phase 9 (Hook) trước
   (audit performance,            → mở khóa Factory
    có thể đang block)            → adopt nhanh hơn
         │
         ▼
   Phase 9 (Hook)
         │
         ▼
   Phase 11 (RAG) — vì user thật cần
```

---

## 6. Khái Niệm Quan Trọng — Cognitive vs Reasoning vs Hook

Để tránh nhầm lẫn khi implement:

| Khái niệm | Vai trò | Khi nào dùng |
|---|---|---|
| **`ryuu-cognitive`** (ReAct/CoT) | LLM tự suy luận | Lúc agent đang nghĩ |
| **`ryuu-reasoning`** (Z3/Prolog) | Solver kiểm tra proof | Sau khi agent ra quyết định |
| **Hook** | Inject Python code vào lifecycle | Bất cứ event nào (pre/post) |

**Tương quan:**
- Cognitive = *cách nghĩ* (generate decision)
- Reasoning = *kiểm tra kết quả* (verify decision)
- Hook = *cơ chế generic* để build cả 2 + audit + metric

Hook + Verifier có overlap (cả 2 inject vào post_execute), nhưng:
- Hook = generic callable, không có retry loop
- Verifier = có semantic rõ (passed/confidence/feedback) + auto refine qua EvaluatorStrategy

---

## 7. Khuyến Nghị Cụ Thể (Action Items Tuần Tới)

**Tuần này (2026-05-21 → 2026-05-28):**
1. ✅ **Audit async** của cost/audit/tracer (1-2 ngày)
2. ✅ **Viết spec chi tiết Hook System** (1 ngày) — dựa trên `docs/guides/hooks.md` đã có
3. ✅ **Tạo task breakdown Phase 9** vào `tasks/todo-phase9-hooks.md`

**Tuần sau (2026-05-28 → 2026-06-04):**
4. Implement Hook MVP (6 events) + tests
5. Tag `v0.2.0a2` (preview release với hooks)

**Lý do thứ tự này:**
- Async audit cần 1-2 ngày, không thể skip (risk cao nếu sai)
- Hook là **foundation** — block Factory, block PII filter, block approval workflow
- Factory không gấp vì class-based đã hoạt động cho early adopters

---

## 8. Liên Kết Đến Tài Liệu Liên Quan

- `docs/guides/quickstart.md` — Factory API design (proposed)
- `docs/guides/hooks.md` — Hook system spec đầy đủ
- `docs/architecture/uaaf-v2-architecture.md` — Architecture v2
- `packages/MIGRATION.md` — Migration history Phase 8.x
- `tasks/todo-phase8-2-uaaf-core.md` — Reference cho task breakdown style

---

**Key point:** Đừng làm `ryuu-reasoning` trước. Cám dỗ vì "novel", nhưng 95% user sẽ không dùng. Hook + Factory + RAG mới là thứ unblock đa số use case.
