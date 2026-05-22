# Apply Migration — Code Analysis Execution Checklist

**Date:** 2026-05-22
**Target ryuu version:** `0.3.0a16`
**Companion to:**
- [Handoff doc](./2026-05-21_llm-react-architecture-uaaf-handoff.md) — existing architecture
- [Migration guide §17](./2026-05-21_migration-to-ryuu.md#17-phase-1111x11y147--concrete-code-analysis-refactor) — playbook

> **Purpose:** Step-by-step actionable PR-by-PR checklist với file paths, ready-to-paste code, verification commands, rollback plans. Run this để execute migration trong 3 weeks.
>
> **Status indicators:** `[ ]` pending, `[x]` done, `[!]` blocked

---

## Pre-Migration

### Environment Setup

```bash
[ ] cd /path/to/code_analysis
[ ] git checkout -b migrate-to-ryuu
[ ] source .venv/bin/activate
[ ] bash /Volumes/.../uaaf-framework/scripts/install-dev.sh
[ ] python -c "import ryuu; print(ryuu.__version__)"
    # Expected: 0.3.0a16
[ ] python -c "from ryuu_knowledge_rag import RAGBackbone; from ryuu_reasoning import RuleVerifier; print('OK')"
```

### Baseline Capture

```bash
[ ] pytest tests/eval/test_chat_intent.py --json-out=baseline-intent.json
[ ] pytest tests/column_crud_matrix_integration/run_all.py --engine llm --json-out=baseline-crud.json
[ ] grep -c "complete_json" src/ | tee baseline-complete-json-count.txt
[ ] git tag pre-migration-baseline
```

---

## PR 1 — Foundation (Week 1, Day 1-5)

**Goal:** LLM bridge + tools migration + 1 project RAG indexed. End state: existing CrudMatrixWorker still works (via bridge), new agents can use RAG.

### 1.1 LLM Bridge (Day 1, 1-2h)

**File:** `src/llm/ryuu_adapter_bridge.py` (NEW)

```python
"""Bridge ryuu ILLMProvider → existing LLMAdapter Protocol."""
from __future__ import annotations
import json
from typing import Any

from ryuu.providers.llm import CompletionRequest, ILLMProvider, Message


class RyuuLLMBridge:
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
        messages: list[Message] = []
        if system_prompt:
            messages.append(Message(role="system", content=system_prompt))
        messages.append(Message(role="user", content=prompt))

        request = CompletionRequest(
            messages=messages,
            model=self.model,
            temperature=0.1,
            response_schema=output_schema,   # ← Phase 11.y forwarded
        )
        response = await self._provider.complete(request)
        self.last_input_tokens = response.usage.input_tokens
        self.last_output_tokens = response.usage.output_tokens

        text = response.content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
        return json.loads(text)

    def describe_status(self) -> str:
        return f"ryuu/{self.model}"
```

**File:** `src/llm/adapter_factory.py` (MODIFY)

```python
# REPLACE existing imports + get_llm_adapter body:
from ryuu._provider_detect import build_provider as ryuu_build_provider
from src.llm.ryuu_adapter_bridge import RyuuLLMBridge


def get_llm_adapter(model: str, config: AppConfig) -> LLMAdapter:
    provider = ryuu_build_provider(model, api_key=config.openai_api_key)
    return RyuuLLMBridge(provider, model)
```

**Verification:**
```bash
[ ] pytest tests/unit/test_react_agent.py -v
[ ] pytest tests/unit/test_crud_matrix_worker.py -v
[ ] python -c "
from src.llm.adapter_factory import get_llm_adapter
from src.config import load_config
adapter = get_llm_adapter('gpt-4o-mini', load_config())
print(adapter.describe_status())  # Expected: ryuu/gpt-4o-mini
"
[ ] git commit -m "feat(llm): bridge to ryuu ILLMProvider"
```

**Rollback:** `git revert HEAD` — bridge isolated, no downstream changes.

### 1.2 Tools Migration (Day 2-3, 3-4h)

**Strategy:** Mode A (callables) for 12 stateless, Mode B (ITool) for 2 stateful.

**File:** `src/chat/agent/tools/_callable_wrappers.py` (NEW)

```python
"""Mode A tool wrappers — callable closures over GraphQueryService."""
from __future__ import annotations
from typing import Any

from src.chat.graph_query_service import GraphQueryService


def make_search_symbols(graph: GraphQueryService):
    async def search_symbols(query: str) -> dict[str, Any]:
        """Full-text search class/method by name."""
        results = await graph.search_symbols(query)
        return {"hits": results, "found": bool(results)}
    return search_symbols


def make_get_class_overview(graph: GraphQueryService):
    async def get_class_overview(class_id: str) -> dict[str, Any]:
        """Properties + methods of a class."""
        return await graph.get_class_overview(class_id)
    return get_class_overview


# ... 10 more — port each Tool subclass to a callable factory
```

**File:** `src/chat/agent/tool_registry_factory.py` (NEW)

```python
"""Wire 14 tools into shared ToolRegistry."""
from ryuu_execution.tool_registry import ToolRegistry

from src.chat.agent.tools._callable_wrappers import (
    make_search_symbols, make_get_class_overview, ...,
)
from src.chat.agent.tools.itool_tools import (
    GetCallSubgraphTool, GetControlFlowsTool,
)
from src.chat.graph_query_service import GraphQueryService


def build_code_analysis_registry(graph: GraphQueryService) -> ToolRegistry:
    registry = ToolRegistry()
    # Mode A — callable + auto schema introspect
    registry.register("search_symbols", make_search_symbols(graph))
    registry.register("get_class_overview", make_get_class_overview(graph))
    # ... 10 more callables

    # Mode B — stateful ITool
    registry.register("get_call_subgraph", GetCallSubgraphTool(graph))
    registry.register("get_control_flows", GetControlFlowsTool(graph))
    return registry
```

**Verification:**
```bash
[ ] python -c "
from src.chat.agent.tool_registry_factory import build_code_analysis_registry
from src.chat.graph_query_service import GraphQueryService
reg = build_code_analysis_registry(GraphQueryService())
print(f'Registered: {len(reg._handlers)} tools')   # Expected: 14
"
[ ] pytest tests/unit/test_tools.py -v
[ ] git commit -m "feat(tools): port 14 tools to ryuu ToolRegistry"
```

### 1.3 Index 1 Project RAG (Day 4, 2-3h)

**File:** `src/chat/rag/project_indexer.py` (NEW)

```python
"""RAG indexing per project_id — pre-populate for chat handler context."""
from __future__ import annotations

from ryuu_knowledge_rag import (
    InMemoryVectorStore, RAGBackbone, RAGPipeline, RecursiveChunker,
)
from ryuu_providers.adapters.openai import OpenAIProvider

from src.chat.graph_query_service import GraphQueryService
from src.config import AppConfig


_BACKBONES: dict[str, RAGBackbone] = {}


async def get_or_index(project_id: str, graph: GraphQueryService, cfg: AppConfig) -> RAGBackbone:
    if project_id in _BACKBONES:
        return _BACKBONES[project_id]

    backbone = RAGBackbone(pipeline=RAGPipeline(
        embedder=OpenAIProvider(api_key=cfg.openai_api_key),
        vector_store=InMemoryVectorStore(),
        chunker=RecursiveChunker(chunk_size=500, overlap=80),
    ))

    # Index classes
    for cls in await graph.list_classes(project_id):
        await backbone.write(
            f"Class {cls.name} ({cls.fqn}): {cls.summary or 'no summary'}. "
            f"Methods: {', '.join(cls.method_names[:10])}",
            scope_key=project_id,
            metadata={"type": "class", "id": cls.id},
        )

    # Index routes
    for route in await graph.list_routes(project_id):
        await backbone.write(
            f"Route {route.method} {route.path}: handler={route.handler}, "
            f"entities={list(route.entities)}",
            scope_key=project_id,
            metadata={"type": "route", "id": route.id},
        )

    _BACKBONES[project_id] = backbone
    return backbone


async def invalidate(project_id: str) -> None:
    """Call after project re-scan to force re-index next access."""
    _BACKBONES.pop(project_id, None)
```

**Verification (use a small test project):**
```bash
[ ] python -c "
import asyncio
from src.chat.rag.project_indexer import get_or_index
from src.chat.graph_query_service import GraphQueryService
from src.config import load_config
async def main():
    backbone = await get_or_index('test-proj', GraphQueryService(), load_config())
    print(f'Index size: {await backbone.pipeline.vector_store.count()} chunks')
    result = await backbone.query('UserController', scope_key='test-proj', top_k=3)
    print(f'Top hit: {result.results[0][:100] if result.results else \"empty\"}')
asyncio.run(main())
"
[ ] git commit -m "feat(rag): per-project indexing with ryuu-knowledge-rag"
```

### 1.4 PR 1 Summary

- [ ] Phase 1 bridge: 1 file new + 1 modified
- [ ] Phase 2 tools: 2 files new, 14 tools ported
- [ ] Phase 11.x indexer: 1 file new
- [ ] All existing tests GREEN
- [ ] **Open PR 1** với title: `feat(migration): foundation — ryuu bridge + tool registry + RAG indexer`

---

## PR 2 — Anti-Hallucination (Week 2, Day 1-5)

**Goal:** Replace 13 JPA if-chains with declarative RuleVerifier + wrap CrudMatrixWorker with Evaluator for self-correcting LLM.

### 2.1 Port JPA Rules to RuleVerifier (Day 1-2, 2h)

**File:** `src/chat/workers/jpa_rules.py` (NEW)

```python
"""13 JPA annotation rules as declarative ryuu_reasoning Rules."""
from ryuu_reasoning import Rule

JPA_ANNOTATION_RULES = [
    Rule(
        name="no_update_on_immutable",
        predicate=lambda d: not (
            d.get("op") == "U" and "updatable=false" in d.get("annotations", [])
        ),
        severity="critical",
        message="@Column(updatable=false) cannot have U op",
    ),
    Rule(
        name="no_create_on_generated",
        predicate=lambda d: not (
            d.get("op") == "C" and "@Generated" in d.get("annotations", [])
        ),
        severity="critical",
        message="@Generated cannot have C op (DB auto-populates)",
    ),
    Rule(
        name="no_delete_on_readonly",
        expression="op != 'D' or 'readonly' not in annotations",
        severity="critical",
        message="@Readonly cannot have D op",
    ),
    # ... 10 more — port from src/chat/workers/crud_matrix_worker.py::_post_validate_annotations
]
```

**File:** `src/chat/workers/crud_matrix_worker.py` (MODIFY)

Replace `_post_validate_annotations` body:
```python
# DELETE old 13-if-chain implementation, REPLACE with:
from ryuu_reasoning import RuleVerifier
from src.chat.workers.jpa_rules import JPA_ANNOTATION_RULES

_jpa_verifier = RuleVerifier(rules=JPA_ANNOTATION_RULES)

async def _post_validate_annotations(self, llm_ops, entity_field_specs):
    """Phase 14.7 — declarative rules thay vì if-chain."""
    import json
    corrected = []
    for op in llm_ops:
        anno = entity_field_specs[op["entity"]][op["column"]]["annotations"]
        op_with_anno = json.dumps({**op, "annotations": list(anno)})
        result = await _jpa_verifier.verify(op_with_anno, self._dummy_ctx())
        if result.passed:
            corrected.append(op)
        else:
            self._audit_logger.log("jpa_violation", {
                "op": op, "feedback": result.feedback,
            })
    return corrected
```

**Verification:**
```bash
[ ] pytest tests/unit/test_post_validate_annotations.py -v
    # All existing test cases should still pass — rule logic unchanged
[ ] pytest tests/column_crud_matrix_integration/run_all.py --engine llm
    # Compare precision/recall vs baseline-crud.json — should be ±2%
[ ] git commit -m "feat(crud): port JPA rules to RuleVerifier (Phase 14.7)"
```

### 2.2 Wrap với Evaluator (Day 3, 2h)

**File:** `src/chat/workers/crud_matrix_worker.py` (MODIFY)

Modify `build_column_matrix_llm()` to wrap LLM call in Evaluator:

```python
from ryuu import Agent, Evaluator
from ryuu_reasoning import RuleVerifier

CRUD_OPS_SCHEMA = {...}   # paste from migration §17.1

async def build_column_matrix_llm(self, project_id, graph, ...):
    # ... existing setup ...

    column_agent = Agent(
        model=model,
        system=load_yaml("crud_matrix_column_classify.v1.yml").system,
        output_schema=CRUD_OPS_SCHEMA,       # Phase 11.y
        adaptive_compute=False,               # disabled — schema is consistent
        audit=True,
    )

    async def rule_check(out: str) -> tuple[bool, str]:
        result = await _jpa_verifier.verify(out, self._dummy_ctx())
        return result.passed, result.feedback

    evaluator = Evaluator(
        generator=column_agent,
        verifier=rule_check,
        max_refines=2,
    )

    for route in routes:
        try:
            answer = await evaluator.run(
                self._build_route_prompt(route, context),
                domain=project_id,
            )
            # answer is final markdown after up to 3 attempts (1 + 2 refines)
            # If schema enforcement holds, parse directly
            raw_ops = json.loads(answer)["ops"]
            corrected = await self._post_validate_annotations(raw_ops, entity_field_specs)
        except Exception as exc:
            emit("route_error", {"route": route.label, "error": str(exc)})
            continue
```

**Verification:**
```bash
[ ] pytest tests/column_crud_matrix_integration/run_all.py --engine llm
    # Should see: fewer route_error events, higher precision (Evaluator refines)
[ ] grep "refine" ryuu_audit.jsonl | wc -l   # count of refine cycles triggered
[ ] git commit -m "feat(crud): wrap LLM call với Evaluator + output_schema"
```

### 2.3 A/B Test (Day 4-5, 4h)

**Setup:** Feature flag để toggle old vs new.

```python
# src/config.py
@dataclass
class AppConfig:
    # ... existing ...
    USE_RYUU_EVALUATOR: bool = False   # flip True to enable
```

```python
# crud_matrix_worker.py
if cfg.USE_RYUU_EVALUATOR:
    raw_ops = await evaluator.run(...)
else:
    raw_ops = await self._adapter_factory(model).complete_json(...)
```

**Run A/B:**
```bash
[ ] export USE_RYUU_EVALUATOR=false
[ ] pytest tests/column_crud_matrix_integration/run_all.py --engine llm \
        --json-out=ab-old.json

[ ] export USE_RYUU_EVALUATOR=true
[ ] pytest tests/column_crud_matrix_integration/run_all.py --engine llm \
        --json-out=ab-new.json

[ ] python scripts/compare_eval.py ab-old.json ab-new.json
    # Expected: new ≥ old precision (RuleVerifier blocks hallucinated ops)
    #           new ≥ old recall (Evaluator refines on failure)
```

**Decision gate:** Only merge PR 2 if new ≥ old on both precision + recall.

### 2.4 PR 2 Summary

- [ ] Phase 14.7 RuleVerifier: 1 file new, 1 modified
- [ ] Phase 11.y output_schema + Evaluator wrap: 1 file modified
- [ ] A/B test passes
- [ ] **Open PR 2** với title: `feat(migration): anti-hallucination — RuleVerifier + Evaluator refine loop`

### 2.5 Port Eval Suites to `ryuu-eval` (Day 5, 4-6h per suite)

> See migration §18 cho details. This sub-step covers chat_intent suite trước
> để có A/B baseline tool ready khi PR 2 ships.

**File:** `tests/eval/test_chat_intent_ryuu.py` (NEW — paste from §18.3)

**Verification:**
```bash
[ ] python tests/eval/test_chat_intent_ryuu.py artifacts/eval/chat_intent_ryuu.json
[ ] python scripts/compare_eval.py \
        baseline-intent.json \
        artifacts/eval/chat_intent_ryuu.json
    # Expected: ≥ baseline pass_rate, comparable cost
```

**Wire into existing SSE endpoint** (`src/api/app.py`):
```python
# Change _SUITE_SCRIPTS:
_SUITE_SCRIPTS = {
    "chat_intent":     "tests/eval/test_chat_intent_ryuu.py",   # ← swap script
    "crud_matrix":     "tests/column_crud_matrix_integration/run_all.py",
    "crud_matrix_llm": "tests/column_crud_matrix_integration/run_all.py --engine llm",
}
```

SSE endpoint vẫn dùng subprocess pattern — chỉ script body chuyển sang ryuu-eval. UI không cần đổi.

```bash
[ ] curl -N http://localhost:8000/api/eval/run/stream/chat_intent
    # Verify event stream still works
[ ] git commit -m "feat(eval): port chat_intent suite to ryuu-eval"
```

**Defer to Week 3 Day 3-4:** crud_matrix + crud_matrix_llm suites (covered in PR 3).

---

## PR 3 — Scale (Week 3, Day 1-5)

**Goal:** Index all projects, wire `knowledge=` into chat handlers, enable adaptive_compute for cost saving.

### 3.1 Index All Projects (Day 1, 4h)

**File:** `src/chat/rag/background_indexer.py` (NEW)

```python
"""Background job: re-index project RAG on commit hook."""
import anyio
from src.chat.rag.project_indexer import invalidate, get_or_index
from src.chat.graph_query_service import GraphQueryService


async def reindex_all_projects(graph: GraphQueryService, cfg) -> None:
    for project_id in await graph.list_projects():
        invalidate(project_id)
        await get_or_index(project_id, graph, cfg)


async def reindex_on_commit(project_id: str, graph: GraphQueryService, cfg) -> None:
    """Called by webhook after project re-scan completes."""
    invalidate(project_id)
    await get_or_index(project_id, graph, cfg)
```

**Wire into existing scan pipeline:**
```python
# src/scan/orchestrator.py (existing scan logic)
from src.chat.rag.background_indexer import reindex_on_commit

async def scan_project(project_id: str):
    # ... existing graph build ...
    await reindex_on_commit(project_id, graph, cfg)   # NEW
```

**Verification:**
```bash
[ ] python -c "
import asyncio
from src.chat.rag.background_indexer import reindex_all_projects
asyncio.run(reindex_all_projects(...))
"
[ ] # Check index size for largest project — should be < 5 minutes
```

### 3.2 Wire `knowledge=` Into Chat Handlers (Day 2, 3h)

**File:** `src/chat/agent/handlers/open_react_handler.py` (MODIFY)

```python
from ryuu import Agent
from src.chat.rag.project_indexer import get_or_index

class OpenReActHandler:
    def __init__(self, intent, graph, answer_worker, adapter_factory, cfg):
        # ... existing ...
        self._cfg = cfg

    async def handle(self, req, decision, ctx):
        backbone = await get_or_index(req.project_id, self._graph, self._cfg)
        tool_registry = build_code_analysis_registry(self._graph)

        agent = Agent(
            model="gpt-4o-mini",
            system=load_yaml(f"{self._intent}.yml").system,
            tool_registry=tool_registry,           # Mode C
            knowledge=backbone,                     # Phase 11.x
            knowledge_budget_tokens=1500,
            knowledge_scope_field="domain",
            max_iterations=8,
            audit=True,
        )

        result = await agent.run(req.message, domain=req.project_id)
        # ... build ChatQueryResponse ...
```

**Verification:**
```bash
[ ] pytest tests/eval/test_chat_intent.py --json-out=after-pr3.json
[ ] python scripts/compare_eval.py baseline-intent.json after-pr3.json
    # Expected: latency -50%, cost -60%, accuracy ≥ baseline
[ ] git commit -m "feat(chat): wire knowledge=RAGBackbone into OpenReActHandler"
```

### 3.3 Enable Adaptive Compute (Day 3, 30m)

**File:** `src/chat/agent/handlers/open_react_handler.py` (MODIFY)

Add to Agent kwargs:
```python
agent = Agent(
    # ... existing ...
    adaptive_compute=True,              # Phase 14.3
    tier_models={
        "trivial": "gpt-4o-mini",
        "medium":  "gpt-4o-mini",
        "hard":    "gpt-4o",
    },
)
```

**Verification:**
```bash
[ ] # Run 100 sample queries
[ ] grep '"difficulty"' ryuu_audit.jsonl | jq -r '.metadata.difficulty' | sort | uniq -c
    # Expected distribution: ~50% trivial/medium, ~10% hard
[ ] # Cost reduction: check ryuu_audit.jsonl total USD vs baseline
[ ] git commit -m "feat(chat): adaptive_compute tier dispatch"
```

### 3.4 Thinking Trail Audit UI (Day 4, 4h)

**File:** `src/chat/agent/handlers/open_react_handler.py` (MODIFY)

```python
agent = Agent(
    # ... existing ...
    thinking_mode=True,                 # Phase 14.1
)
result = await agent.run(req.message, domain=req.project_id)

# Pass thinking to SSE event for UI display
event_callback("thinking_trail", {
    "reasoning": result.thinking,
    "answer": result.output,
})
```

**File:** `src/api/routers/chat.py` (MODIFY SSE handler)

Add new event type to forward thinking events to client.

**Verification:**
```bash
[ ] # Manual: open chat UI, ask a query, verify thinking panel shows reasoning
[ ] curl -N -X POST http://localhost:8000/api/chat/query/stream \
        -d '{"project_id": "test", "message": "explain login"}'
    # Look for `event: thinking_trail` in SSE stream
[ ] git commit -m "feat(chat): expose thinking trail via SSE for audit UI"
```

### 3.5a Port CRUD Eval Suites to ryuu-eval (Day 3-4, 6-8h)

> See migration §18.4 cho code template. CRUD matrix suite có custom Scorer
> (`CrudPrecisionRecall`) — port carefully để preserve scoring semantics.

**File:** `tests/column_crud_matrix_integration/run_all_ryuu.py` (NEW)

Copy template from migration §18.4. Adapt fixture loading + scorer threshold
theo existing eval suite conventions.

**Verification:**
```bash
[ ] python tests/column_crud_matrix_integration/run_all_ryuu.py \
        artifacts/eval/crud_matrix_ryuu.json --engine llm
[ ] python scripts/compare_eval.py \
        baseline-crud.json \
        artifacts/eval/crud_matrix_ryuu.json
    # Expected: ≥ baseline precision/recall (RuleVerifier blocks bad ops)
```

**Update SSE endpoint** to use new script:
```python
# src/api/app.py
_SUITE_SCRIPTS = {
    "chat_intent":     "tests/eval/test_chat_intent_ryuu.py",
    "crud_matrix":     "tests/column_crud_matrix_integration/run_all_ryuu.py",
    "crud_matrix_llm": "tests/column_crud_matrix_integration/run_all_ryuu.py --engine llm",
}
```

**Add Markdown renderer** cho PR comment bot:
```python
# scripts/eval_to_pr_comment.py (NEW)
from ryuu_eval.renderers import MarkdownRenderer
import json, sys

suite_json = json.load(open(sys.argv[1]))
# Reconstruct SuiteResult from JSON (helper utility needed)
# ... write markdown ...
```

```bash
[ ] git commit -m "feat(eval): port crud_matrix suites to ryuu-eval + Markdown renderer"
```

### 3.5 Performance Benchmark (Day 5, 4h)

```bash
[ ] python scripts/bench_chat.py --queries=200 --output=bench-after.json
[ ] python scripts/compare_bench.py baseline-bench.json bench-after.json
    # Report: cost, latency p50/p95, accuracy
[ ] # If acceptable:
[ ] git tag migration-complete-v1
[ ] # Open PR 3 với benchmark results in description
```

### 3.6 PR 3 Summary

- [ ] Phase 11 indexing: 1 file new, integration into scan pipeline
- [ ] Phase 11.x `knowledge=`: 1 file modified (handler)
- [ ] Phase 14.3 `adaptive_compute=`: kwarg added
- [ ] Phase 14.1 `thinking_mode=`: kwarg + SSE event
- [ ] Performance benchmark recorded
- [ ] **Open PR 3** với title: `feat(migration): scale — RAG indexing + adaptive compute + thinking trail`

---

## PR 4 — Ingestion Pipeline (Week 4, Day 1-5)

**Goal:** Optimize ingestion pipeline LLM calls (largest cost driver — ~3000 calls/project).
**Note:** Phase 1 bridge (PR 1.1) đã auto-migrate ingestion to ryuu providers. PR 4 chỉ adds **optimizations** (output_schema, BatchRunner, RAG).

> See migration §19 cho rationale + audit table.

### 4.1 Verify Phase 1 Bridge Covers Ingestion (Day 1, 1-2h)

After PR 1 ships, ingestion phases automatically use ryuu. Verify smoke test:

```bash
[ ] # Run small project ingestion end-to-end
[ ] python -m src.cli ingest --project test-proj --source /path/to/small-repo
[ ] # Verify completes without errors
[ ] grep "ryuu/" logs/ingestion.log    # confirms RyuuLLMBridge in use
[ ] # Check costs match baseline (no regression)
```

### 4.2 Add `output_schema` to Phase 1/1b/1c Prompts (Day 1-2, 6-9h)

**File:** `src/llm/prompt_registry.py` (MODIFY)

For each of `class_enhancement_batch_prompt`, `route_extraction_batch_prompt`,
`method_call_extraction_batch_prompt`:

1. Define JSON Schema describing expected output structure
2. Add `output_schema: dict | None = None` field to `PromptDef`
3. Populate for the 3 batch prompts (skip per-class fallback if needed)

**Code template** (see migration §19.3 for CLASS_ENHANCEMENT_BATCH).

**Files MODIFY:**
- `src/llm/prompt_registry.py` — add output_schema field + 3 new schemas
- `src/phases/phase1_class_enhancement.py` — pass `output_schema=prompt.output_schema`
  in `complete_json()` calls (replace `output_schema=None`)
- `src/phases/phase1b_route_extraction.py` — same
- `src/phases/phase1c_method_calls.py` — same

**Verification:**
```bash
[ ] # Run ingestion on test project — should see fewer parse_errors trong logs
[ ] grep "parse_error" logs/ingestion.log | wc -l
    # Compare baseline. Expected: -50% to -90% parse errors (strict mode enforces shape)
[ ] git commit -m "feat(ingest): add output_schema to phase1/1b/1c prompts (Phase 11.y)"
```

### 4.3 Migrate Phase 1/1b/1c to `BatchRunner` (Day 3-4, 9-12h)

> Optional but recommended. Replaces manual `asyncio.gather` với ryuu BatchRunner.
> Benefit: cost cap, OpenAI Batch API option (50% discount cho commit-triggered ingestion),
> per-item progress callbacks, exponential backoff retry.

**Per-phase pattern** (apply to phase1, phase1b, phase1c):

```python
# Before (current pattern in phase1_class_enhancement.py)
batch_tasks = [self._process_class(cls) for cls in batch]
batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)

# After
from ryuu import Agent, BatchRunner, BatchItem

agent = Agent(
    model="gpt-4o-mini",
    system=CLASS_ENHANCEMENT_BATCH.system_prompt,
    output_schema=CLASS_ENHANCEMENT_BATCH.output_schema,
)
items = [
    BatchItem(input=cls.to_prompt(), metadata={"class_id": cls.id})
    for cls in batch
]
runner = BatchRunner(
    agent=agent,
    budget_usd=5.0,                       # auto-abort if exceeded
    max_concurrent=20,                     # rate limit
    progress_callback=lambda item, result: emit_event(
        "phase1_progress", {"class_id": item.metadata["class_id"]}
    ),
)
batch_results = await runner.run(items)
# OR for non-realtime (overnight indexer):
# batch_results = await runner.run(items, mode="openai_batch")   # 50% discount
```

**Verification:**
```bash
[ ] # Run ingestion với BatchRunner
[ ] # Check cost report
[ ] # Verify progress events fire per-class (not per-batch)
[ ] # If overnight scheduled: enable mode="openai_batch", verify 50% cost reduction
[ ] git commit -m "feat(ingest): migrate batch processing to ryuu BatchRunner"
```

### 4.4 Phase 2 Insight Derivation với `Agent(knowledge=...)` (Day 5, 3h)

> Reuse RAG backbone từ PR 3.2 — same `project_backbones[project_id]` cache.

**File:** `src/phases/phase2_gold_insight_derivation.py` (MODIFY)

```python
from ryuu import Agent
from src.chat.rag.project_indexer import get_or_index

# Replace adapter call in run() method:
async def run(self, project_id, routes, ...):
    backbone = await get_or_index(project_id, self.graph, self.cfg)
    insight_agent = Agent(
        model=self.cfg.openai_model,
        system=phase2_insight_prompt.system_prompt,
        output_schema=phase2_insight_prompt.output_schema,
        knowledge=backbone,
        knowledge_budget_tokens=1500,
        knowledge_scope_field="domain",
    )

    for route in routes:
        result = await insight_agent.run(
            f"Generate insight for route {route.method} {route.path}",
            domain=project_id,
        )
        insight = result.parsed
        await self.graph.store_insight(route.id, insight)
```

**Verification:**
```bash
[ ] # Run ingestion on test project
[ ] # Compare insight quality vs baseline (manual review of 5-10 cases)
[ ] # Verify RAG cache hit — should not re-index
[ ] git commit -m "feat(ingest): Phase 2 insight derivation dùng knowledge="
```

### 4.5 PR 4 Summary

- [ ] Phase 1 bridge auto-covered ingestion (verified smoke test)
- [ ] Phase 11.y `output_schema=` on 3 batch prompts (parse error reduction)
- [ ] Phase 12 `BatchRunner` for batch processing (cost cap + optional Batch API)
- [ ] Phase 11.x `knowledge=` for Phase 2 insight derivation (RAG reuse)
- [ ] **Open PR 4** với title: `feat(migration): ingestion pipeline optimization — output_schema + BatchRunner + RAG`

---

## Post-Migration

### Cleanup

```bash
[ ] # Remove dead code:
[ ] git rm src/chat/agent/react_agent.py     # if replaced by ryuu Agent
[ ] git rm src/chat/agent/handler_registry.py   # if replaced by Router
[ ] # Remove old adapter implementations if bridge satisfies all callers
[ ] # Keep CrudMatrixWorker — domain logic stays
```

### Documentation

```bash
[ ] Update README.md với ryuu integration note
[ ] Archive old handoff doc (rename _archived_):
    git mv examples/code_analysis/docs/2026-05-21_llm-react-architecture-uaaf-handoff.md \
           examples/code_analysis/docs/_archived_2026-05-21_pre-migration-architecture.md
```

### Monitoring (Week 4+)

```bash
[ ] Set up alerts on ryuu_audit.jsonl size growth (compliance trail)
[ ] Monitor BudgetExceededError rate (should be < 1%)
[ ] Track RAG cache hit rate (target > 80%)
[ ] Quarterly: re-index all projects after ryuu version upgrade
```

---

## Rollback Plan

### Per-PR Rollback

| PR | Risk | Rollback Action |
|---|---|---|
| PR 1 (Foundation) | Low — bridge isolated | `git revert <PR1>` — restores old adapter |
| PR 2 (Anti-hallucination) | Medium — changes CrudMatrixWorker | Toggle `USE_RYUU_EVALUATOR=false` (feature flag stays) |
| PR 3 (Scale) | Medium — chat handlers | Toggle `KNOWLEDGE_ENABLED=false` |

### Emergency Full Rollback

```bash
[ ] git checkout pre-migration-baseline
[ ] # Restart services
[ ] # Notify team
```

---

## Effort Tracking

| Phase | Estimated | Actual | Owner |
|---|---|---|---|
| PR 1.1 Bridge | 1-2h | _____ | _____ |
| PR 1.2 Tools | 3-4h | _____ | _____ |
| PR 1.3 RAG indexer | 2-3h | _____ | _____ |
| PR 2.1 JPA rules | 2h | _____ | _____ |
| PR 2.2 Evaluator wrap | 2h | _____ | _____ |
| PR 2.3 A/B test | 4h | _____ | _____ |
| PR 2.5 Eval chat_intent → ryuu-eval | 4-6h | _____ | _____ |
| PR 3.1 Index all | 4h | _____ | _____ |
| PR 3.2 knowledge= | 3h | _____ | _____ |
| PR 3.3 adaptive | 30m | _____ | _____ |
| PR 3.4 thinking trail | 4h | _____ | _____ |
| PR 3.5a Eval CRUD → ryuu-eval | 6-8h | _____ | _____ |
| PR 3.5 Benchmark | 4h | _____ | _____ |
| PR 4.1 Ingestion smoke test | 1-2h | _____ | _____ |
| PR 4.2 Ingestion output_schema (3 phases) | 6-9h | _____ | _____ |
| PR 4.3 Ingestion BatchRunner | 9-12h | _____ | _____ |
| PR 4.4 Phase 2 knowledge= | 3h | _____ | _____ |
| **Total** | **56-70h** | _____ | _____ |

---

## Success Metrics

Capture these post-migration vs baseline:

| Metric | Baseline | Target | Actual |
|---|---|---|---|
| Cost per chat query | _____ | -50% to -75% | _____ |
| p50 latency | _____ | -30% to -50% | _____ |
| Intent classification accuracy | _____ | ≥ baseline | _____ |
| CRUD matrix precision (column LLM) | _____ | ≥ baseline | _____ |
| Hallucinated JPA ops caught | _____ | 100% (RuleVerifier) | _____ |
| Audit trail coverage | _____ | 100% | _____ |
| LOC removed (vs added) | 0 | net -500 to -800 LOC | _____ |

---

## Open Questions

Track unresolved decisions:

- [ ] Vector store choice for production (InMemory → Chroma vs Qdrant)?
- [ ] Index TTL — re-index on every commit OR daily batch?
- [ ] Should thinking trail be user-visible in UI OR audit-only?
- [ ] `adaptive_compute` tier defaults OK OR need custom per-intent?
- [ ] Streaming via `Agent.stream()` — port now OR defer post-migration?
- [ ] Move budget_usd cap to per-user OR per-project?
- [ ] Eval subprocess pattern — keep OR switch to in-process (`EvalRunner` directly từ FastAPI handler)?
- [ ] Custom `CrudPrecisionRecall` Scorer — upstream to ryuu-eval package?
- [ ] EvalPage UI — extend to show `precision/recall` breakdown từ `ScoreResult.reason`?
- [ ] Ingestion `output_schema` — define schemas for all 3 batch phases OR start với class_enhancement only?
- [ ] OpenAI Batch API mode (50% discount, 24h SLA) — enable cho commit-triggered indexing?
- [ ] Existing `llm_ctx(phase=, run_id=)` context — preserve via ryuu hooks OR rely on `audit=True` jsonl?
- [ ] Phase 2 RAG context — share backbone với chat OR separate index (different chunking strategy)?

---

## Contact / Escalation

- **Framework questions:** ryuu maintainer (this repo)
- **Domain questions:** code_analysis tech lead
- **Production rollout:** SRE on-call rotation
