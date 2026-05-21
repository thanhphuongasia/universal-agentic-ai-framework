# Prompt + Tool Modularization

← [Quickstart Index](README.md) | [All guides](../)

> Production-grade structure: YAML versioning, file-based prompts, tool registry với DI + security, responsibility split RYUU vs Product, hot-swap version no code change.

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

