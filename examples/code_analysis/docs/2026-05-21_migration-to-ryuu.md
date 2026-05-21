# Code Analysis → RYUU Migration Guide

**Date:** 2026-05-21
**Companion to:** [`2026-05-21_llm-react-architecture-uaaf-handoff.md`](./2026-05-21_llm-react-architecture-uaaf-handoff.md)
**Target ryuu version:** `0.3.0a11`
**Purpose:** Step-by-step playbook để migrate hệ thống code_analysis (orchestrator + ReAct + handlers + workers + SSE API) sang ryuu framework. Hướng dẫn này giả định bạn đã đọc handoff doc + có quyền sửa source `src/llm/`, `src/chat/`, `src/api/`.

---

## 1. TL;DR — Mapping Tóm Tắt

| Component hiện tại | ryuu equivalent | Approach |
|---|---|---|
| `LLMAdapter` Protocol + impls | `ILLMProvider` (ryuu_providers.llm) + adapters | **Bridge** giữ `complete_json` API |
| `adapter_factory(model)` callable | `ryuu._provider_detect.build_provider(model)` | Wrap qua bridge |
| `Tool` ABC + 14 tool classes | `ITool` Protocol HOẶC callable (Tool Mode B/A) | Direct port |
| `GraphReActAgent` (sync loop) | `ryuu.Agent` Factory (async, built-in ReAct) | **Replace** — loop có sẵn |
| `IntentHandler` × 5 (OpenReAct) | 1 `Agent` per intent + shared `tool_registry` | Inline với Mode C |
| `CrudMatrixHandler` (no ReAct) | `Agent` với `instructions` cho structured output | Direct |
| `HandlerRegistry.dispatch` | `Router(routes=..., analyzer=...)` facade | **Replace** |
| `ChatOrchestrator` (1183 lines) | Compose Router + Evaluator + custom orchestrator | Hybrid |
| `progress_hook` per-route | `Agent.stream()` events + custom worker callback | Bridge |
| `cancel_check: Callable[[], bool]` | `anyio.create_task_group().cancel_scope` | Refactor |
| `event_callback` thinking events | `verbose=True` (stdout) HOẶC custom hook `pre_llm/post_llm` | Hooks |
| YAML prompts | `PromptRegistry` (`ryuu.prompts.registry`) | Direct — same YAML format works |
| Cost / token observability | `budget_usd`, `audit=True`, `trace=True` Factory kwargs | Wire qua Factory |

**Effort revised:** Handoff ước tính 17-21h. Với Factory + facades + Mode C tool registry (Phase 10.3), giảm còn **~10-14h** vì:
- KHÔNG cần viết ReAct loop (built-in `LLMAgent._react_loop`)
- KHÔNG cần viết HandlerRegistry (dùng `Router` facade)
- KHÔNG cần thread bridge (ryuu async-first)
- Tool registration đơn giản hơn (Mode A callable hoặc Mode B ITool)

---

## 2. Phase-by-Phase Migration

```
Phase 1: LLM Adapter Bridge        (1-2h, isolated)
Phase 2: Tool Migration            (3-4h, parallelizable per tool)
Phase 3: Replace ReAct Agent       (1h, mostly delete code)
Phase 4: Handlers → Router         (2-3h)
Phase 5: Orchestrator Refactor     (2-3h)
Phase 6: SSE Streaming + Cancel    (2h)
Phase 7: Eval Integration          (1h, mostly no-op)
                                    ────────
                                    11-16h total
```

---

## 3. Phase 1 — LLM Adapter Bridge

**Goal:** Wrap ryuu `ILLMProvider` để satisfy existing `LLMAdapter` Protocol. KHÔNG đụng downstream code.

### 3.1 Bridge Implementation

```python
# src/llm/ryuu_adapter_bridge.py — NEW FILE
"""Bridge: ryuu ILLMProvider → existing LLMAdapter Protocol.

Lets ReAct agent + CrudMatrixWorker keep using `complete_json()` while
backend swaps to ryuu providers.
"""

from __future__ import annotations

import json
from typing import Any

from ryuu.providers.llm import CompletionRequest, ILLMProvider, Message


class RyuuLLMBridge:
    """Implements existing LLMAdapter Protocol via ryuu ILLMProvider."""

    def __init__(self, provider: ILLMProvider, model: str) -> None:
        self._provider = provider
        self.model = model
        self.enabled = True
        self.last_input_tokens = 0
        self.last_output_tokens = 0

    async def complete_json(
        self,
        prompt: str,
        system_prompt: str | None = None,
        output_schema: dict | None = None,
        schema_name: str | None = None,
    ) -> dict:
        """Async — same signature as LLMAdapter.complete_json()."""
        messages: list[Message] = []
        if system_prompt:
            messages.append(Message(role="system", content=system_prompt))
        messages.append(Message(role="user", content=prompt))

        request = CompletionRequest(
            messages=messages,
            model=self.model,
            temperature=0.1,
            # ryuu CompletionRequest doesn't have response_format yet;
            # rely on system_prompt + JSON Schema in user prompt to enforce.
            # When ryuu adds structured output support, plug here.
        )
        response = await self._provider.complete(request)
        self.last_input_tokens = response.usage.input_tokens
        self.last_output_tokens = response.usage.output_tokens

        # Parse — accept raw JSON or fenced ```json blocks
        text = response.content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
        return json.loads(text)

    def describe_status(self) -> str:
        return f"ryuu/{self.model}"
```

### 3.2 Update Factory

```python
# src/llm/adapter_factory.py — MODIFY
from ryuu._provider_detect import build_provider as ryuu_build_provider
from src.llm.ryuu_adapter_bridge import RyuuLLMBridge


def get_llm_adapter(model: str, config: AppConfig) -> LLMAdapter:
    """Return adapter for the given model. Now ryuu-backed."""
    # Old direct OpenAI/Anthropic instantiation → replaced
    provider = ryuu_build_provider(model, api_key=config.openai_api_key)
    return RyuuLLMBridge(provider, model)
```

### 3.3 Verify Nothing Else Breaks

```bash
# All existing callers — react_agent, crud_matrix_worker — should work
pytest tests/unit/test_react_agent.py
pytest tests/unit/test_crud_matrix_worker.py
```

**Pass:** Phase 1 done. Downstream code untouched.

**Caveat:** ryuu chưa có structured output (JSON Schema enforcement) — rely on prompt-level instruction. Nếu cần strict JSON, add post-parse validation hoặc wait for ryuu structured output feature.

---

## 4. Phase 2 — Tool Migration

### 4.1 Two Options per Tool

Current `Tool` ABC:
```python
class Tool(ABC):
    name: str
    description: str
    parameters: dict   # JSON Schema
    @abstractmethod
    def run(self, args: dict, ctx: AgentContext) -> ToolResult: ...
```

#### Option A — Stateless Tools → Callable (ryuu Mode A)

For tools không cần `ctx` (e.g. `SearchSymbolsTool` chỉ query graph):

```python
# Before
class SearchSymbolsTool(Tool):
    def __init__(self, graph: GraphQueryService):
        self._graph = graph
    name = "search_symbols"
    description = "Full-text search class/method by name"
    parameters = {"type": "object", "properties": {"query": {"type": "string"}}}
    def run(self, args, ctx) -> ToolResult:
        results = self._graph.search_symbols(args["query"])
        return ToolResult(tool_name=self.name, found=bool(results), output={"hits": results})

# After (callable + closure over graph)
def make_search_symbols(graph: GraphQueryService):
    async def search_symbols(query: str) -> dict:
        """Full-text search class/method by name."""
        results = await graph.search_symbols(query)
        return {"hits": results, "found": bool(results)}
    return search_symbols

# Usage in Agent:
agent = Agent(tools=[make_search_symbols(graph), make_other_tool(graph), ...])
```

ryuu auto-extracts schema từ docstring + type hints.

#### Option B — Stateful Tools → ITool (ryuu Mode B)

For tools cần shared state hoặc complex schema:

```python
from ryuu_execution.tool_registry import ITool

class GetCallSubgraphTool:
    """ITool — stateful, has explicit schema."""

    tool_id = "get_call_subgraph"
    schema = {
        "type": "function",
        "function": {
            "name": "get_call_subgraph",
            "description": "Method call graph to depth N",
            "parameters": {
                "type": "object",
                "properties": {
                    "method_id": {"type": "string"},
                    "depth": {"type": "integer", "default": 3},
                },
                "required": ["method_id"],
            },
        },
    }

    def __init__(self, graph: GraphQueryService):
        self._graph = graph

    async def execute(self, args: dict[str, Any]) -> Any:
        return await self._graph.get_call_subgraph(
            method_id=args["method_id"],
            depth=args.get("depth", 3),
        )
```

### 4.2 Pre-build ToolRegistry (Mode C)

```python
# src/chat/agent/tool_registry_factory.py — NEW
from ryuu_execution.tool_registry import ToolRegistry

from src.chat.agent.tools.callable_tools import (
    make_search_symbols, make_get_class_overview, ...
)
from src.chat.agent.tools.itool_tools import (
    GetCallSubgraphTool, GetControlFlowsTool, ...
)


def build_code_analysis_registry(graph: GraphQueryService) -> ToolRegistry:
    """Wire all 14 tools with shared graph dependency."""
    registry = ToolRegistry()
    # Mode A — callables
    registry.register("search_symbols", make_search_symbols(graph))
    registry.register("get_class_overview", make_get_class_overview(graph))
    registry.register("get_class_relationships", make_get_class_relationships(graph))
    registry.register("get_dependency_neighbors", make_get_dependency_neighbors(graph))
    registry.register("get_path_between_symbols", make_get_path_between_symbols(graph))
    registry.register("get_entities_for_class_or_route", make_get_entities(graph))
    registry.register("get_repository_interactions", make_get_repo_interactions(graph))
    registry.register("resolve_route", make_resolve_route(graph))
    registry.register("search_routes_fuzzy", make_search_routes_fuzzy(graph))
    registry.register("find_routes_by_use_case", make_find_routes_by_use_case(graph))
    registry.register("find_method_by_name", make_find_method_by_name(graph))
    registry.register("get_project_overview", make_get_project_overview(graph))

    # Mode B — stateful ITool
    registry.register("get_call_subgraph", GetCallSubgraphTool(graph))
    registry.register("get_control_flows", GetControlFlowsTool(graph))
    return registry
```

### 4.3 Handle Tool Result Mapping

Current `ToolResult` has `needs_clarification` field — ryuu's tool dispatch doesn't have this concept. Two options:

**Option 1**: Return as dict, agent treats as data:
```python
async def resolve_route(name: str) -> dict:
    matches = await graph.resolve(name)
    if len(matches) > 1:
        return {
            "needs_clarification": True,
            "candidates": [m.path for m in matches],
        }
    return {"resolved": matches[0].id}
```

Agent's downstream code checks `result.get("needs_clarification")`.

**Option 2**: Raise custom exception caught by hook:
```python
class NeedsClarification(Exception):
    def __init__(self, candidates: list[str]):
        self.candidates = candidates

# Hook handles
async def needs_clarification_hook(ctx: OnErrorContext) -> None:
    if isinstance(ctx.error, NeedsClarification):
        # Emit clarification SSE event, halt agent
        await emit_clarification(ctx.error.candidates)
```

Option 1 simpler — recommended.

---

## 5. Phase 3 — Replace ReAct Agent

### 5.1 Delete `react_agent.py` (mostly)

ryuu's `LLMAgent._react_loop` (in `ryuu_execution.llm_agent`) đã cover:
- Thought → Action → Observation loop
- Tool dispatch via `ToolRegistry`
- Max iterations cap
- Token budget tracking

→ **Xoá**:
- `src/chat/agent/react_agent.py::ReActAgent` (abstract)
- `src/chat/agent/react_agent.py::GraphReActAgent`
- `_run_coro_sync` thread bridge (ryuu async-first)
- Manual prompt loading + tool schema building

### 5.2 Replace Với Factory `Agent()`

```python
# Before
agent = GraphReActAgent(
    adapter_factory=adapter_factory,
    prompt_key="REACT_AGENT_PROMPT_V1",
    model="gpt-4o-mini",
    heuristic_fn=heuristic,
    tools=tool_dict,
    max_steps=8,
)
result = agent.run(ctx)   # sync, returns AgentRunResult

# After
from ryuu import Agent

agent = Agent(
    model="gpt-4o-mini",
    instructions=REACT_SYSTEM_PROMPT,    # load same YAML, extract system_prompt
    tool_registry=tool_registry,         # Mode C — shared registry
    max_iterations=8,
    temperature=0.1,
    verbose=True,                        # log Thought/Action/Observation
)
result = await agent.run(user_message)   # async, returns AgentResult
```

### 5.3 Heuristic Fallbacks → Hook

Cũ: `_heuristic_reason()` chạy khi LLM disabled.

ryuu approach: hook `pre_llm` chuyển hướng nếu provider là FakeLLM:

```python
from ryuu.hooks import PreLLMContext

async def maybe_use_heuristic(ctx: PreLLMContext):
    if not has_openai_key():
        # Inject canned response, skip LLM call
        # (Or use FakeLLMProvider that returns heuristic output)
        ...

agent = Agent(..., hooks={"pre_llm": [maybe_use_heuristic]})
```

Hoặc đơn giản hơn: dùng FakeLLMProvider với pre-staged responses cho dev mode (same pattern todo_app/factory_demo.py).

### 5.4 AgentContext → ryuu scope kwargs

```python
# Before
ctx = AgentContext(project_id=pid, message=msg, ...)
result = agent.run(ctx)

# After
result = await agent.run(
    msg,
    user_id=session_user_id,
    session_id=request_id,
    domain="code_analysis",   # → ContextScope cho cost tracking per-project
)
```

`project_id` chuyển vào `domain` hoặc custom kwarg passed qua `scope_kwargs`.

---

## 6. Phase 4 — Handlers → Router

### 6.1 5 OpenReAct Intents → 5 Agents Behind Router

```python
# Before
for intent in OPEN_REACT_INTENTS:   # symbol_explain, dependency_analysis, ...
    registry.register(OpenReActHandler(intent, graph, answer_worker, adapter_factory))

# After
from ryuu import Agent, Router

tool_registry = build_code_analysis_registry(graph)   # shared across all agents

intent_agents = {
    "symbol_explain": Agent(
        model="gpt-4o-mini",
        instructions=load_yaml("symbol_explain.v1.yml").system,
        tool_registry=tool_registry,
        max_iterations=8,
    ),
    "dependency_analysis": Agent(
        model="gpt-4o-mini",
        instructions=load_yaml("dependency_analysis.v1.yml").system,
        tool_registry=tool_registry,
        max_iterations=8,
    ),
    # ... 3 more
}

# Intent classifier → route key
def classify_intent(message: str) -> str:
    return intent_classifier.classify(message).intent

router = Router(routes=intent_agents, analyzer=classify_intent)

# Single entry point
result = await router.run(user_message, user_id=..., session_id=...)
```

### 6.2 CrudMatrixHandler — Keep As-Is

Handler không dùng ReAct, just deterministic 3-phase pipeline. **Không cần migrate** — chỉ thay `adapter_factory` bằng bridge (đã làm Phase 1).

```python
matrix_worker = CrudMatrixWorker(adapter_factory=adapter_factory)  # unchanged signature
```

### 6.3 Diagram Handlers → Same Pattern

3 diagram handlers (`SequenceDiagramHandler`, `ClassDiagramHandler`, `EntityDiagramHandler`) đều dùng `GraphReActAgent` với tool subset. Migrate same as OpenReAct:

```python
diagram_agents = {
    "sequence": Agent(model="gpt-4o-mini", instructions=..., tool_registry=route_tool_subset, max_iterations=4),
    "class": Agent(model="gpt-4o-mini", instructions=..., tool_registry=class_tool_subset, max_iterations=4),
    "entity": Agent(model="gpt-4o-mini", instructions=..., tool_registry=entity_tool_subset, max_iterations=4),
}
```

---

## 7. Phase 5 — Orchestrator Refactor

### 7.1 ChatOrchestrator (1183 lines) → Compose

Original:
```
ChatOrchestrator
  ├─ IntentClassifier
  ├─ SlotExtractor
  ├─ HandlerRegistry → 6 handlers
  └─ multi_intent_merge logic
```

Refactored composition:
```python
# src/chat/orchestrator_ryuu.py — NEW
from ryuu import Router

class ChatOrchestrator:
    def __init__(self, graph, intent_classifier, slot_extractor):
        self._graph = graph
        self._intent_classifier = intent_classifier
        self._slot_extractor = slot_extractor

        tool_registry = build_code_analysis_registry(graph)

        # 5 OpenReAct agents + 3 diagram agents + 1 crud handler
        self._open_react = {intent: Agent(...) for intent in OPEN_REACT_INTENTS}
        self._diagram = {kind: Agent(...) for kind in ("sequence", "class", "entity")}
        self._crud_handler = CrudMatrixHandler(graph, matrix_worker, answer_worker)

        # Unified routing
        all_agents = {**self._open_react, **self._diagram, "crud_matrix": self._crud_handler}
        self._router = Router(routes=all_agents, analyzer=self._classify)

    def _classify(self, message: str) -> str:
        decision = self._intent_classifier.classify(message)
        return decision.intent

    async def chat(self, req: ChatQueryRequest) -> ChatQueryResponse:
        # Multi-intent? — sequential dispatch + merge
        intents = await self._classify_multi(req.message)
        responses = [await self._router.run(req.message) for _ in intents]
        return self._merge_multi_intent(responses)
```

**Loại bỏ ~600 lines** trùng lặp (handler wiring, registry mgmt).

### 7.2 Multi-Intent Merge — Keep Custom Logic

Multi-intent là domain-specific logic, không có facade nào cover. **Giữ nguyên** `_merge_multi_intent()` method.

---

## 8. Phase 6 — SSE Streaming + Cancel

### 8.1 Replace `event_callback` Với `Agent.stream()`

```python
# Before
async def chat_stream_endpoint(req):
    ctx = AgentContext(event_callback=emit_to_sse, ...)
    response = await orchestrator.chat(req, ctx)

# After
@app.post("/api/chat/query/stream")
async def chat_stream(req: ChatQueryRequest):
    async def event_gen():
        async for event in agent_for_intent(req).stream(req.message):
            yield f"data: {json.dumps({
                'type': event.type,            # 'thought' / 'tool_call' / 'tool_result' / 'final'
                'text': event.text,
                'tool_name': event.tool_name,
                'args': event.args,
                'result': event.result,
            })}\n\n"
    return StreamingResponse(event_gen(), media_type="text/event-stream")
```

### 8.2 Replace `progress_hook` (CrudMatrixWorker) — Keep Custom Queue

`CrudMatrixWorker.build_column_matrix_llm()` emits **worker-level** progress events (per-route, not per-LLM-call). ryuu's `Agent.stream()` chỉ cover agent lifecycle.

→ **Giữ nguyên** `progress_hook: Callable[[dict], None]` cho CrudMatrixWorker. KHÔNG migrate sang ryuu hook.

```python
# Vẫn dùng pattern cũ
worker.build_column_matrix_llm(
    progress_hook=lambda evt: queue.put_nowait(evt),
    cancel_check=cancel_event.is_set,
)
```

### 8.3 Cancellation Token

ryuu chưa có built-in cancellation token. 2 cách:

**Option A**: anyio `CancelScope`
```python
import anyio

async def chat_with_cancel(req, cancel_event):
    with anyio.CancelScope() as scope:
        cancel_event.add_callback(scope.cancel)
        result = await agent.run(req.message)
        return result
```

**Option B**: Custom hook `pre_llm` checks cancel flag
```python
async def cancel_check_hook(ctx: PreLLMContext):
    if cancel_event.is_set():
        raise asyncio.CancelledError("client disconnect")

agent = Agent(..., hooks={"pre_llm": [cancel_check_hook]})
```

Option A cleaner — recommended.

---

## 9. Phase 7 — Eval Integration

Eval system (`tests/column_crud_matrix_integration/run_all.py`) **không phụ thuộc agent framework** — chạy subprocess + compare với golden expectations.

→ **Không thay đổi gì**, ngoại trừ:
- `--engine llm` mode: subprocess sẽ dùng new `adapter_factory` (ryuu-backed) tự động qua Phase 1 bridge

Optional improvement (future): refactor eval to use `ryuu-eval` package (Phase 7 standalone) cho metrics + cost tracking unified.

---

## 10. Observability Bonus (Free với ryuu)

Original code không có built-in cost tracking, audit, trace. Migrate xong, bật miễn phí:

```python
agent = Agent(
    model="gpt-4o-mini",
    instructions=...,
    tool_registry=tool_registry,
    max_iterations=8,

    # ── NEW: free observability ──
    budget_usd=1.0,            # raise BudgetExceededError if session cost > $1
    rate_limit_rps=10,         # token-bucket per-scope
    audit=True,                # JSONL hash chain → ./ryuu_audit.jsonl
    trace=True,                # OpenTelemetry spans → console / OTLP

    # Custom hooks
    hooks={
        "pre_tool":  [pii_scrub_hook],      # NEW capability
        "post_tool": [graph_query_metric],   # NEW capability
        "on_error":  [sentry_report_hook],   # NEW capability
        "on_budget_exceeded": [alert_oncall],
    },
)
```

---

## 11. Common Pitfalls

| Pitfall | Symptom | Fix |
|---|---|---|
| Tool returns sync `dict` instead of `Awaitable[dict]` | `TypeError: object dict can't be used in 'await' expression` | Define handler as `async def` |
| Response không phải JSON khi `complete_json()` parse | `JSONDecodeError` | Strict prompt: "Return ONLY valid JSON. No prose." + post-parse validate |
| LLM trả tool name không tồn tại | `ToolRegistry.run() returns {"error": "Unknown tool"}` | LLM thấy error → tự correct ở vòng sau (ReAct loop) |
| ContextScope không pass project_id | Cost tracking gộp chung | Pass `domain=project_id` qua `.run(..., domain=project_id)` |
| Thread bridge bị remove → `RuntimeError: no running event loop` | Caller code đang sync | Wrap caller bằng `asyncio.run()` hoặc convert sang async |
| Cancel không propagate xuống Neo4j queries | Query vẫn chạy sau khi client disconnect | Pass `cancel_event` xuống GraphQueryService, check before query |

---

## 12. Migration Checklist

```
Phase 1 — LLM Bridge (1-2h)
[ ] Create src/llm/ryuu_adapter_bridge.py
[ ] Update src/llm/adapter_factory.py
[ ] pytest tests/unit/test_react_agent.py → still GREEN
[ ] pytest tests/unit/test_crud_matrix_worker.py → still GREEN

Phase 2 — Tools (3-4h)
[ ] Refactor 12 stateless tools → callable + closure (Mode A)
[ ] Refactor 2 stateful tools → ITool (Mode B)
[ ] Create src/chat/agent/tool_registry_factory.py
[ ] Unit test: build_code_analysis_registry(graph) returns 14 handlers
[ ] Verify tool schema via Agent(tools=[...]).agent._agent.tool_registry._handlers

Phase 3 — Replace ReAct (1h)
[ ] Delete src/chat/agent/react_agent.py (or stub for compat)
[ ] Remove _run_coro_sync thread bridge
[ ] Update OpenReActHandler/SequenceDiagramHandler to construct ryuu Agent

Phase 4 — Handlers → Router (2-3h)
[ ] Build intent_agents dict (5 OpenReAct + 3 diagram)
[ ] Create Router(routes=..., analyzer=intent_classifier.classify)
[ ] Keep CrudMatrixHandler unchanged (no ReAct)
[ ] Remove HandlerRegistry class

Phase 5 — Orchestrator (2-3h)
[ ] Refactor ChatOrchestrator.chat() to use Router
[ ] Keep _merge_multi_intent() logic
[ ] Update tests/integration/test_orchestrator.py

Phase 6 — SSE + Cancel (2h)
[ ] /api/chat/query/stream uses Agent.stream() → SSE events
[ ] CrudMatrixWorker progress_hook UNCHANGED
[ ] Cancel via anyio.CancelScope (replace threading.Event)

Phase 7 — Eval (1h, mostly no-op)
[ ] Verify run_all.py --engine llm uses new adapter_factory (ryuu-backed)
[ ] Optional: migrate to ryuu-eval package

Production rollout
[ ] Side-by-side run old vs new on 100 sample queries
[ ] Compare: latency, accuracy, cost per query
[ ] Smoke test SSE streaming end-to-end
[ ] Enable budget_usd=X.XX in prod config
[ ] Enable audit=True for compliance trail
```

---

## 13. Code Sample Repository

Reference impl ở:
- **Factory + tool registry**: `examples/todo_app/factory_demo.py` (170 lines, same pattern)
- **Multi-agent Chain**: `examples/code_analysis/agents.py` + `workflow.py` (current class-based)
- **Hook integration**: `tests/unit/ryuu/test_hooks_9_2.py` (PRE/POST_TOOL examples)
- **SSE streaming**: `examples/todo_app/server.py` (FastAPI + QueueCallbacks)

---

## 14. Quy Trình Install RYUU Cho Project Code Analysis

Editable install vì cùng máy + cần edit cả 2:

```bash
# Trong code_analysis venv (giả sử đã có)
cd /path/to/code_analysis
source .venv/bin/activate

# Install ryuu editable
bash /Volumes/COMPANY\ DATA/.../uaaf-framework/scripts/install-dev.sh

# Verify
python -c "from ryuu import Agent, Router, BatchRunner; print('OK')"
```

App's `pyproject.toml`:
```toml
[project]
name = "code-analysis"
dependencies = [
    "ryuu",                      # editable install satisfies this
    "fastapi>=0.115",
    "neo4j>=5.20",
    # ... other app deps
]
```

Sửa code ryuu → app thấy ngay (no reinstall). Move ryuu folder sau này → reinstall, app unchanged.

---

## 15. Câu Hỏi Còn Mở

1. **Structured output** (JSON Schema enforcement): ryuu chưa có. CrudMatrixWorker.build_column_matrix_llm() rely on `output_schema` rất chặt. Workaround: prompt-level "Return ONLY valid JSON matching schema {...}". Hoặc đợi feature add to ryuu (~Phase 11+).

2. **Multi-intent dispatch**: ryuu Router pick 1 route. Multi-intent flow vẫn cần custom logic ở orchestrator level. Có thể dùng `FanOut(agents=[a1, a2])` nếu các intents độc lập.

3. **Heuristic fallbacks**: 2 cách (FakeLLMProvider với pre-staged responses; hoặc pre_llm hook redirect). Decide based on testability needs.

4. **Tool cancellation**: anyio CancelScope vs threading.Event. Quyết định khi refactor `GraphQueryService` to async (nếu hiện sync).

5. **Cost per project_id**: Use `domain` kwarg → `ContextScope.domain` aggregates cost. Check `CostTracker.get_usage(scope_key=f"user-X:session-Y:proj-Z")`.

---

**Next step**: Bắt đầu Phase 1 (bridge) — isolated, low-risk, unlocks tất cả phases sau.

---

## 16. Claude-like Thinking Patterns Cho Intent Analysis

Áp dụng 5 patterns ưu tiên (từ "Thinking Engine" tổng hợp) vào IntentClassifier + multi-intent flow. Tham khảo reference impl ở `examples/code_analysis/intent_patterns_demo.py`.

> **⚠️ Framework roadmap awareness**: 4/5 patterns đang được promote từ "consumer self-impl"
> → **framework built-in** ở Phase 14.1-14.6 (xem `tasks/plan-phase14-thinking-patterns.md`).
> Đoạn dưới đây giữ self-impl version để bạn chạy ngay với ryuu hiện tại (0.3.0a11).
> Sau khi 0.3.0a12 ship, refactor dùng built-ins (xem §16.10).

### 16.1 Bảng Ưu Tiên

| # | Pattern | Effort | Cost Impact | Quality Impact | Priority |
|---|---|---|---|---|---|
| **#10** | Least-to-Most via `Orchestrator` (multi-intent) | 2-3h | +0% | Unblock multi-intent | 🔴 HIGH |
| **#3+#4** | Compute-Adaptive via `ModelTier` | 1-2h | **-40 → -60%** | Same | 🔴 HIGH |
| **#6+#7** | Best-of-N (low-confidence only) | 2h | +0.1% | Anti-flap | 🟡 MEDIUM |
| **#1+#2** | Thinking Channel (audit trail) | 1h | +1-2% | Debuggability | 🟡 MEDIUM |
| **#9** | Step-Back hierarchical classify | 2h | +1% | +10-20% accuracy | 🟢 LOW-MED |

**Khuyến nghị order:** #10 → #3+#4 → #1+#2 → #6+#7 (conditional) → #9

### 16.2 Pattern #10 — Multi-Intent Orchestrator

`Orchestrator` facade thay `_merge_multi_intent` if-chain. Main agent decompose plan, workers spawn per intent, aggregate merge:

```python
multi_intent = Orchestrator(
    main=Agent(model="gpt-4o-mini", instructions=DECOMPOSE_PROMPT),
    plan_items=lambda out: json.loads(out)["intents"],
    workers=lambda intent: intent_agents[intent["type"]],
    aggregate=merge_multi_intent_responses,   # giữ custom merge
)
```

→ Workers run parallel via anyio task_group → **50% latency reduction** trên multi-intent.

### 16.3 Pattern #3+#4 — Compute-Adaptive (Biggest Win)

Difficulty classifier (cheap gpt-4o-mini, 5 tokens) → pick model tier:

```python
DIFFICULTY_TO_AGENT = {
    "trivial": Agent(model="gpt-4o-mini", max_iterations=2, max_tokens=300),
    "medium":  Agent(model="gpt-4o-mini", max_iterations=4, max_tokens=800),
    "hard":    Agent(model="gpt-4o",       max_iterations=8, max_tokens=2000),
}
```

Apply ngay vào ChatOrchestrator dispatch. Cost saving **40-60%** trên total volume vì >50% queries là trivial/medium.

### 16.4 Pattern #6+#7 — Best-of-N Conditional

Chỉ apply khi intent confidence < 0.8 (avoid wasting cost trên easy classifications):

```python
async def adaptive_intent_classify(message: str) -> str:
    primary = await classifier.run(message)   # single call
    confidence = extract_confidence(primary)
    if confidence >= 0.8:
        return parse_intent(primary)
    # Low-confidence: best-of-3 vote
    fanout = FanOut(agents=[classifier_t09, classifier_t09, classifier_t09])
    samples = await fanout.run(message)
    return majority_vote([s.output for s in samples])
```

Cost: extra ~$0.0003 per low-conf query. Anti-flap improvement: **30-50%**.

### 16.5 Pattern #1+#2 — Thinking Channel (Audit Trail)

Force classifier output `<thinking>` + `<answer>`. Log thinking to audit:

```python
classifier = Agent(
    model="gpt-4o-mini",
    instructions="""
        Classify intent.
        <thinking>What keywords? What ambiguity? Why eliminate alternatives?</thinking>
        <answer>{intent_type}</answer>
    """,
)
intent, reasoning = parse_thinking_answer(await classifier.run(message))
audit_logger.log("intent_decision", {"chosen": intent, "reasoning": reasoning})
```

Production user support: trả lời "tại sao chat chọn intent X" qua audit log lookup.

### 16.6 Pattern #9 — Step-Back Hierarchical Classify

Thay flat 8-way → 2-stage (category → specific):

```python
# Stage 1: 3 categories (structure | behavior | data)
category = await category_classifier.run(message)   # 5 tokens

# Stage 2: Pick specific intent within category (max 4 options)
specific_intent = await specific_classifier.run(
    message, category=category, options=INTENT_BY_CATEGORY[category]
)
```

Mỗi classifier solve smaller decision space → **+10-20% accuracy** trên ambiguous queries.

### 16.7 Compose Full Pipeline

Reference: `examples/code_analysis/intent_patterns_demo.py` `production_intent_chat()` shows all 5 composed.

### 16.8 Patterns KHÔNG Áp Dụng Cho Intent Layer

| Pattern | Lý do bỏ |
|---|---|
| **#12 OODA Subagent** | Intent classify là 1-shot, không có loop |
| **#20+#27 REPL feedback** | Intent classify không sinh code |
| **#29 Adversarial Probe** | Cost quá lớn cho mỗi intent call |
| **#30 Architect-Editor** | Intent classify quá nhỏ, không cần split |
| **#31 Linter in Loop** | Không applicable |

Áp dụng những patterns này ở downstream (tools generation, code suggestion), không phải intent.

### 16.9 Migration Order Cụ Thể

```
Tuần 1: Pattern #10 + #3+#4 (HIGH priority)
  Day 1-2: #10 multi-intent Orchestrator
           → Refactor _merge_multi_intent
           → Verify với eval suite (tests/eval/test_chat_intent.py)
  Day 3-4: #3+#4 ModelTier integration
           → Difficulty classifier
           → 3-tier agent pool
           → Measure cost reduction qua audit log

Tuần 2: Pattern #1+#2 + #6+#7 (MEDIUM)
  Day 1: #1+#2 Thinking Channel
           → Log to audit_logger
           → UI debug panel hiển thị reasoning
  Day 2-3: #6+#7 Best-of-N
           → Confidence threshold detection
           → A/B test trên ambiguous query subset

Tuần 3: Pattern #9 (LOW-MED, optional)
  Day 1-2: Step-Back hierarchical
           → Define category mapping
           → 2-stage classifier
           → Compare accuracy với baseline
```

### 16.10 Future Built-In Usage (Sau Khi Phase 14.x Ship)

Khi ryuu 0.3.0a12 ship Phase 14.1-14.6, refactor code analysis dùng built-in thay self-impl. Giảm **~200 lines/pattern × 4 = 800 lines** code maintenance trên app side.

#### Before/After Comparison

**Pattern #1+#2 Thinking Channel:**

```python
# BEFORE (self-impl, current §16.5)
classifier = Agent(
    model="gpt-4o-mini",
    instructions="""
        Classify intent.
        <thinking>...</thinking>
        <answer>{intent}</answer>
    """,
)
raw = (await classifier.run(message)).output
thinking = re.search(r"<thinking>(.*?)</thinking>", raw, re.DOTALL)
answer = re.search(r"<answer>(.*?)</answer>", raw, re.DOTALL)
intent = answer.group(1).strip() if answer else raw

# AFTER (Phase 14.1 built-in)
classifier = Agent(
    model="gpt-4o-mini",
    instructions="Classify intent",
    thinking_mode=True,        # ← framework injects template + parses
)
result = await classifier.run(message)
intent = result.output           # already parsed from <answer>
reasoning = result.thinking      # already parsed from <thinking>
```

**Pattern #3+#4 Adaptive Compute:**

```python
# BEFORE (self-impl §16.3)
DIFFICULTY_TO_AGENT = {
    "trivial": Agent(model="gpt-4o-mini", max_iterations=2, max_tokens=300),
    "medium":  Agent(model="gpt-4o-mini", max_iterations=4, max_tokens=800),
    "hard":    Agent(model="gpt-4o",       max_iterations=8, max_tokens=2000),
}
async def adaptive_dispatch(message):
    diff = await classifier.run(message)
    return await DIFFICULTY_TO_AGENT[diff.output.strip()].run(message)

# AFTER (Phase 14.3 built-in)
agent = Agent(
    model="gpt-4o-mini",
    instructions="...",
    adaptive_compute=True,                # ← framework dispatches internally
    tier_models={"trivial": "gpt-4o-mini", "medium": "gpt-4o-mini", "hard": "gpt-4o"},
    tier_max_iterations={"trivial": 2, "medium": 4, "hard": 8},
)
result = await agent.run(message)        # difficulty classified + dispatched auto
```

**Pattern #6+#7 Best-of-N:**

```python
# BEFORE (self-impl §16.4)
primary = await classifier.run(message)
confidence = extract_confidence(primary.output)
if confidence < 0.8:
    fanout = FanOut(agents=[classifier]*3)
    samples = await fanout.run(message)
    winner = Counter(samples).most_common(1)[0][0]
else:
    winner = parse_intent(primary.output)

# AFTER (Phase 14.2 built-in)
from ryuu import BestOfN
best = BestOfN(
    agent=classifier,
    n=3,
    vote="majority",
    confidence_threshold=0.8,             # ← framework handles gate
)
winner = await best.run(message)
```

**Pattern #9 Step-Back Hierarchical:**

```python
# BEFORE (self-impl §16.6)
category = (await category_classifier.run(message)).output.strip()
options = INTENT_BY_CATEGORY[category]
specific = Agent(instructions=f"Pick one of: {options}")
intent = (await specific.run(message)).output.strip()

# AFTER (Phase 14.4 built-in)
from ryuu import HierarchicalRouter
router = HierarchicalRouter(
    category_classifier=category_agent,
    routes_by_category={
        "structure": {"symbol_explain": s_agent, "dep_analysis": d_agent, ...},
        "behavior":  {"sequence_diagram": seq_agent, ...},
        "data":      {"crud_matrix": crud_agent, ...},
    },
    fallback_route="symbol_explain",
)
result = await router.run(message)        # 2-stage handled internally
```

#### Migration Order Sau Khi Phase 14.x Ship

```
Step 1: Verify ryuu version ≥ 0.3.0a12
        pip show ryuu

Step 2: Refactor IntentClassifier (Pattern #1+#2)
        - Remove regex parse code
        - Add thinking_mode=True kwarg
        - Update audit_logger to read result.thinking
        Effort: 30m

Step 3: Refactor ChatOrchestrator adaptive dispatch (Pattern #3+#4)
        - Remove DIFFICULTY_TO_AGENT dict
        - Single Agent with adaptive_compute=True
        Effort: 1h

Step 4: Refactor low-confidence path (Pattern #6+#7)
        - Replace manual FanOut+vote với BestOfN facade
        Effort: 30m

Step 5: Refactor hierarchical classify (Pattern #9, optional)
        - Replace 2-stage manual với HierarchicalRouter
        Effort: 1h

Total: ~3h to clean up code after Phase 14.x ship
```

#### Why Framework, Không Phải Product

| Aspect | Self-impl (current §16.2-16.6) | Framework built-in (Phase 14.x) |
|---|---|---|
| LOC trong app | ~200/pattern × 4 = 800 lines | ~5/pattern × 4 = 20 lines |
| Test coverage | App-specific tests | Framework 22 tests, all apps inherit |
| Bug surface | Mỗi app re-impl → tiềm năng bug | Framework hardened 1 lần |
| Upgrade flow | App phải sửa khi pattern improve | Bump ryuu version → all benefits |
| Cross-app consistency | Khác nhau (todo, code_analysis, stock_advisory) | Same behavior, audit comparable |
| Onboarding | Đọc 200-line pattern code | Đọc kwarg doc |

→ Framework provides **mechanism** (parse, dispatch, vote, hierarchy), consumer provides **policy/config** (category mapping, tier ranges, score functions). Đúng separation of concern.

### 16.11 Tracking Phase 14.x Status

- **Plan**: `tasks/plan-phase14-thinking-patterns.md`
- **Roadmap**: `tasks/roadmap-phase8.8-to-14.md` § "Phase 14.1-14.6"
- **Estimated ship**: 1 week (~14h)
- **Version**: 0.3.0a12

Khi 0.3.0a12 ship, follow §16.10 migration steps để clean up.

