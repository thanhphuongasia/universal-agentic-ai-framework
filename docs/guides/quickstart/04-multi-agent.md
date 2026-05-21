# Multi-Agent Patterns

← [Quickstart Index](README.md) | [All guides](../)

> 5 patterns + facades: Chain, FanOut (3 variants), Router, Orchestrator, Evaluator. Compose freely via uniform `.run(input)→output` interface.

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

