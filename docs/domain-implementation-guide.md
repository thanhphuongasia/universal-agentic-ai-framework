# UAAF Domain Implementation Guide

> **Reference implementation**: `examples/code_analysis/` — runs end-to-end in demo mode with no API key.
> **Pattern**: Ingest → Analyse (multi-agent) → Summarize → (optional) Verify

---

## Overview

Every UAAF domain follows the same 5-file layout + 1 YAML prompt file:

```
examples/my_domain/
├── ingestion.py       # Parse raw input → typed domain objects
├── tools.py           # Tool handlers (Python callables the LLM can call)
├── agents.py          # Per-item agent + orchestrator + CodebaseReport-equivalent
├── workflow.py        # WorkflowEngine states (IState protocol dataclasses)
├── main.py            # Entry point: wire workflow, run, print results
└── prompts/
    └── my_domain/
        └── v1.yaml    # Prompt templates + tool schemas (versioned)
```

The framework provides the plumbing. Your job is to fill in the five files.

---

## Step 1 — Define your domain objects (`ingestion.py`)

**Pattern**: raw source → typed dataclass with a `to_context_text()` method.

```python
# examples/my_domain/ingestion.py
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ItemInfo:
    """One unit your agents will analyze (class, document, trade, etc.)."""
    name: str
    source: str         # file path, URL, raw text, etc.
    content: str        # the actual data to analyze

    # Complexity signal — used for priority sorting in tools.py
    @property
    def complexity_score(self) -> int:
        return len(self.content.split())  # replace with domain-specific metric

    def to_context_text(self) -> str:
        """Text fed into GraphBackbone — what agents see as context."""
        return f"ITEM: {self.name}\nSource: {self.source}\n{self.content[:500]}"


class MyIngester:
    """Parse raw input → list[ItemInfo]."""

    def ingest(self, source: Path | str) -> list[ItemInfo]:
        # Replace with your parsing logic
        raise NotImplementedError
```

**Code Analysis reference**: `ClassInfo`, `MethodInfo`, `PythonIngester` — parses Python AST.

---

## Step 2 — Write the prompt YAML (`prompts/my_domain/v1.yaml`)

```yaml
# prompts/my_domain/v1.yaml
version: "1.0"
description: "My domain — per-item analysis + summary"
model: "gpt-4o-mini"
temperature: 0.0
max_tokens: 512

prompts:
  analyze_item:
    system: |
      You are an expert in {domain}. Analyze the item and return ONLY valid JSON.

      Required JSON schema:
      {{
        "name": "ItemName",
        "score": 42,
        "label": "HIGH|MEDIUM|LOW",
        "issues": ["specific issue"],
        "suggestion": "One concrete action."
      }}

      Item data:
      ---
      {context}
      ---
    user: "Analyze: {item_name}"

  summarize:
    system: |
      You are a tech lead reviewing analysis results.
      Write a concise summary — 4 bullets, then 3 action items. Under 200 words.
    user: |
      {total} items analyzed. HIGH={high}, MEDIUM={medium}, LOW={low}.
      Coverage: {coverage_pct}%. Provide executive summary and top 3 action items.

tools:
  - name: get_item_details
    description: "Get full metadata for a specific item."
    parameters:
      type: object
      properties:
        item_name: {type: string, description: "Exact item name (case-sensitive)"}
      required: [item_name]

  - name: find_high_priority
    description: "Find items that need immediate attention."
    parameters:
      type: object
      properties:
        min_score: {type: integer, default: 40}
        label: {type: string, enum: [HIGH, MEDIUM, LOW, all], default: "all"}
      required: []
```

**Rules**:
- Use `{{` `}}` for literal braces in JSON schema examples (Jinja2 escaping).
- Variable names in `{braces}` are filled by `PromptRegistry.build_request(cfg, "analyze_item", item_name=..., context=...)`.
- `include_tools=True` → PromptRegistry injects the `tools:` section as OpenAI tool schemas.
- `include_tools=False` → LLM returns raw JSON (faster for per-item analysis).

---

## Step 3 — Write tool handlers (`tools.py`)

Tools are plain `async def` functions. The LLM calls them by name; the framework executes them.

```python
# examples/my_domain/tools.py
from __future__ import annotations
import json
from typing import Any
from examples.my_domain.ingestion import ItemInfo
from uaaf.execution.tool_registry import ToolRegistry  # or copy tools.py pattern


def build_registry(items: list[ItemInfo], reports: list[dict[str, Any]]) -> ToolRegistry:
    registry = ToolRegistry()
    item_map = {i.name: i for i in items}
    report_map = {r.get("name", ""): r for r in reports}

    async def get_item_details(item_name: str) -> dict[str, Any]:
        item = item_map.get(item_name)
        if item is None:
            return {"error": f"Not found: {item_name}", "available": list(item_map)[:10]}
        return {
            "name": item.name,
            "source": item.source,
            "score": item.complexity_score,
            "report": report_map.get(item.name, {}),
        }

    async def find_high_priority(min_score: int = 40, label: str = "all") -> dict[str, Any]:
        candidates = [
            {"name": i.name, "score": i.complexity_score, **report_map.get(i.name, {})}
            for i in items
            if i.complexity_score >= min_score
            and (label == "all" or report_map.get(i.name, {}).get("label") == label)
        ]
        candidates.sort(key=lambda c: c["score"], reverse=True)
        return {"count": len(candidates), "items": candidates[:20]}

    registry.register("get_item_details", get_item_details)
    registry.register("find_high_priority", find_high_priority)
    return registry
```

**Code Analysis reference**: `build_code_registry()` in `tools.py` — wires `get_class_details`, `find_refactor_candidates`, `get_module_summary`.

---

## Step 4 — Write the per-item agent (`agents.py`)

Each agent handles **one item**. They run in parallel via `AgentPool.fan_out`.

```python
# examples/my_domain/agents.py — per-item agent
from __future__ import annotations
import json, os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from examples.my_domain.ingestion import ItemInfo
from uaaf._testing.fakes import FakeLLMProvider
from uaaf.execution.agent import AgentResult, BaseAgent, Task
from uaaf.execution.pool import AgentPool
from uaaf.knowledge.context_assembler import ContextAssembler
from uaaf.knowledge.graph.backbone import GraphBackbone
from uaaf.observability.cost import Cost
from uaaf.prompts.registry import PromptRegistry
from uaaf.providers.llm import ILLMProvider, Response, TokenUsage
from uaaf.runtime.context import ExecutionContext

_PROMPTS_ROOT = Path(__file__).parent / "prompts"
_registry = PromptRegistry(prompts_root=_PROMPTS_ROOT)


# ── Fake LLM for demo mode (no API key needed) ────────────────────────────

def _build_fake_llm(item: ItemInfo) -> FakeLLMProvider:
    """Deterministic response per item — used when OPENAI_API_KEY is absent."""
    issues = []
    if item.complexity_score > 200:
        issues.append(f"High complexity score ({item.complexity_score})")

    analysis = json.dumps({
        "name": item.name,
        "score": item.complexity_score,
        "label": "HIGH" if item.complexity_score > 200 else "MEDIUM" if item.complexity_score > 50 else "LOW",
        "issues": issues,
        "suggestion": "Review and refactor." if issues else "Looks good.",
    })
    return FakeLLMProvider(responses=[
        Response(content=analysis, model="gpt-4o-mini",
                 usage=TokenUsage(80, 60), finish_reason="stop")
    ])


# ── Per-item agent ────────────────────────────────────────────────────────

@dataclass
class ItemAnalysisAgent(BaseAgent):
    llm: ILLMProvider = field(default_factory=lambda: FakeLLMProvider(responses=[]))
    assembler: ContextAssembler = field(default_factory=lambda: ContextAssembler(GraphBackbone()))
    item_info: ItemInfo | None = field(default=None)

    async def _execute(self, task: Task, context: ExecutionContext) -> AgentResult:
        item = self.item_info
        if item is None:
            raise ValueError("item_info not set")

        # 1. Write to shared GraphBackbone — other agents can query this
        scope_key = context.scope.domain
        await self.assembler.write(observation=item.to_context_text(), scope_key=scope_key)

        # 2. Retrieve related context
        assembled = await self.assembler.assemble(
            query=f"{item.name} complexity",
            scope_key=scope_key,
            budget_tokens=1500,
        )

        # 3. Load prompt + call LLM
        cfg = _registry.load("my_domain", "v1")
        request = _registry.build_request(
            cfg, "analyze_item",
            include_tools=False,   # JSON response directly — no tool loop
            context=assembled.text,
            item_name=item.name,
        )
        response = await self.llm.complete(request)

        # 4. Parse JSON (strip markdown fences if present)
        content = response.content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1]) if len(lines) > 2 else content
        try:
            report = json.loads(content)
        except json.JSONDecodeError:
            report = {"name": item.name, "error": "parse failed", "raw": content[:200]}

        out_tokens = response.usage.output_tokens if response.usage else 60
        return AgentResult(
            task_id=task.task_id,
            output=json.dumps(report),
            cost=Cost(
                input_tokens=assembled.token_count + 80,
                output_tokens=out_tokens,
                usd=round((assembled.token_count + 80 + out_tokens) * 0.00000015, 8),
                provider="openai",
                model=cfg.model,
            ),
        )


# ── Orchestrator ──────────────────────────────────────────────────────────

@dataclass
class DomainOrchestrator:
    shared_backbone: GraphBackbone = field(default_factory=GraphBackbone)
    max_concurrency: int = 8

    async def analyse(
        self,
        items: list[ItemInfo],
        base_context: ExecutionContext,
        agent_factory: "AgentFactory",
    ) -> "DomainReport":
        import time
        start = time.monotonic()

        pool = AgentPool(max_concurrency=self.max_concurrency)
        for item in items:
            agent = agent_factory.build(item, shared_backbone=self.shared_backbone)
            pool.register(agent)

        tasks = [
            Task(task_id=f"item-{item.name}", payload={"name": item.name})
            for item in items
        ]
        results_raw = await pool.fan_out(tasks, base_context, on_error="collect")

        reports: list[dict[str, Any]] = []
        errors: list[str] = []
        for item, ar in zip(items, results_raw, strict=True):
            if ar.success and ar.output:
                try:
                    reports.append(json.loads(ar.output))
                except (json.JSONDecodeError, TypeError):
                    errors.append(f"{item.name}: parse failed")
            else:
                errors.append(f"{item.name}: {ar.metadata.get('error', 'unknown')}")

        return DomainReport(
            item_reports=reports,
            errors=errors,
            total_items=len(items),
            elapsed_seconds=time.monotonic() - start,
        )


# ── Result container ──────────────────────────────────────────────────────

@dataclass
class DomainReport:
    item_reports: list[dict[str, Any]]
    errors: list[str]
    total_items: int
    elapsed_seconds: float

    def high_priority(self) -> list[dict[str, Any]]:
        return [r for r in self.item_reports if r.get("label") == "HIGH"]

    def print_summary(self) -> None:
        print(f"\n  Analysed : {len(self.item_reports)}/{self.total_items} items")
        print(f"  Errors   : {len(self.errors)}")
        print(f"  Time     : {self.elapsed_seconds:.2f}s (parallel)")
        for r in self.high_priority()[:5]:
            print(f"    🔴 {r['name']}: {'; '.join(r.get('issues', []))}")


# ── AgentFactory ──────────────────────────────────────────────────────────

@dataclass
class AgentFactory:
    _shared_llm: ILLMProvider | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            from uaaf.providers.adapters.openai import OpenAIProvider
            self._shared_llm = OpenAIProvider(api_key=api_key)  # type: ignore[assignment]

    def build(self, item: ItemInfo, shared_backbone: GraphBackbone) -> ItemAnalysisAgent:
        from examples._utils import silent_tracer
        from uaaf.observability.audit import AuditLogger
        from uaaf.observability.cost import CostPolicy, CostTracker
        from uaaf.observability.rate_limit import RateLimiter, RatePolicy

        llm: ILLMProvider = (
            self._shared_llm if self._shared_llm is not None
            else _build_fake_llm(item)
        )

        return ItemAnalysisAgent(
            agent_id=f"analyst-{item.name}",
            llm=llm,
            assembler=ContextAssembler(shared_backbone),
            item_info=item,
            cost_tracker=CostTracker(CostPolicy()),
            tracer=silent_tracer(),
            audit_logger=AuditLogger(),
            rate_limiter=RateLimiter(RatePolicy()),
        )
```

**Key decisions**:
- `include_tools=False` for per-item analysis → LLM returns JSON directly (faster, cheaper).
- `include_tools=True` for orchestrator-level queries → LLM calls tools to explore results.
- `on_error="collect"` in `fan_out` → one failed agent doesn't kill the rest.
- `AgentFactory` shares one `OpenAIProvider` instance (stateless HTTP; safe to share across 88 agents).

---

## Step 5 — Write WorkflowEngine states (`workflow.py`)

Each state is a plain `@dataclass` implementing `IState` (protocol: needs `state_id` + `execute()`).

```python
# examples/my_domain/workflow.py
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from examples.my_domain.agents import AgentFactory, DomainOrchestrator, DomainReport, build_provider
from examples.my_domain.ingestion import MyIngester
from uaaf.knowledge.graph.backbone import GraphBackbone
from uaaf.prompts.registry import PromptRegistry
from uaaf.runtime.context import ExecutionContext
from uaaf.workflow.state_machine import StateTransition

_PROMPTS_ROOT = Path(__file__).parent / "prompts"


@dataclass
class IngestState:
    state_id: str = "ingest"

    async def execute(self, input: Any, context: ExecutionContext) -> StateTransition:
        source = Path(input) if isinstance(input, str) else Path(".")
        items = MyIngester().ingest(source)
        print(f"  [ingest]    {len(items)} items extracted")
        return StateTransition(next_state="analyse", output=items)


@dataclass
class AnalyseState:
    state_id: str = "analyse"
    max_concurrency: int = 8
    backbone: GraphBackbone = field(default_factory=GraphBackbone)  # public: caller can query after run

    async def execute(self, input: Any, context: ExecutionContext) -> StateTransition:
        items = input
        orchestrator = DomainOrchestrator(
            shared_backbone=self.backbone,
            max_concurrency=min(self.max_concurrency, max(1, len(items))),
        )
        report = await orchestrator.analyse(items, context, AgentFactory())
        print(f"  [analyse]   {len(report.item_reports)}/{report.total_items} in {report.elapsed_seconds:.2f}s")
        return StateTransition(next_state="summarize", output=report)


@dataclass
class SummarizeState:
    state_id: str = "summarize"

    async def execute(self, input: Any, context: ExecutionContext) -> StateTransition:
        report: DomainReport = input
        llm = build_provider()   # OpenAI or FakeLLMProvider depending on env
        registry = PromptRegistry(prompts_root=_PROMPTS_ROOT)
        cfg = registry.load("my_domain", "v1")

        label_dist: dict[str, int] = {}
        for r in report.item_reports:
            k = r.get("label", "LOW")
            label_dist[k] = label_dist.get(k, 0) + 1

        request = registry.build_request(
            cfg, "summarize",
            include_tools=False,
            total=len(report.item_reports),
            high=label_dist.get("HIGH", 0),
            medium=label_dist.get("MEDIUM", 0),
            low=label_dist.get("LOW", 0),
            coverage_pct=0,  # replace with your domain metric
        )
        response = await llm.complete(request)
        print(f"  [summarize] {len(response.content)} chars")
        return StateTransition(next_state=None, output=response.content)  # next_state=None → terminal
```

**Checkpoint contract**:
- `WorkflowEngine` saves a checkpoint AFTER each state completes.
- If the process is killed mid-state, re-run resumes from the LAST completed checkpoint.
- `output` is serialized with `json.dumps` → must be JSON-serializable if using `FileCheckpointStore`. Use `InMemoryCheckpointStore` for dev.

---

## Step 6 — Write the entry point (`main.py`)

```python
# examples/my_domain/main.py
from __future__ import annotations
import asyncio, sys
from pathlib import Path
from typing import Any

from examples.my_domain.workflow import AnalyseState, IngestState, SummarizeState
from examples.my_domain.tools import build_registry
from uaaf.runtime.context import ContextScope, ExecutionContext
from uaaf.workflow.engine import WorkflowEngine
from uaaf.workflow.state_machine import Workflow
from uaaf.workflow.stores.in_memory import InMemoryCheckpointStore


async def main(source: str | None = None) -> None:
    analyse_state = AnalyseState()   # keep ref so we can access backbone after run

    workflow = Workflow(
        workflow_id="my-domain-001",
        states={
            "ingest":    IngestState(),
            "analyse":   analyse_state,
            "summarize": SummarizeState(),
        },
        initial_state="ingest",
        terminal_states=frozenset(),  # engine detects terminal by next_state=None
    )

    store = InMemoryCheckpointStore()
    engine = WorkflowEngine(checkpoint_store=store)
    ctx = ExecutionContext(
        scope=ContextScope(user_id="user", session_id="session-1", domain="my_domain"),
        correlation_id="demo-001",
    )

    result = await engine.run(workflow, initial_input=source, context=ctx)
    print(f"\n  status={result.status.value}  checkpoints={result.checkpoints_saved}")

    if result.status.value != "completed":
        print(f"  ERROR: {result.error}")
        return

    # Extract checkpoint outputs by sequence
    history = await store.load_history("my-domain-001")
    items = history[0].output      # IngestState output
    report = history[1].output     # AnalyseState output → DomainReport
    summary: str = result.output   # SummarizeState output

    report.print_summary()
    print("\n" + summary)

    # Tool demo (shows what the LLM would call)
    registry = build_registry(items, report.item_reports)
    result_str = await registry.run({
        "id": "t1",
        "function": {"name": "find_high_priority", "arguments": {"min_score": 30}}
    })
    import json
    print(f"\n  Tool demo → {result_str[:300]}")


if __name__ == "__main__":
    src = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--source" else None
    asyncio.run(main(source=src))
```

---

## Architecture Decision Reference

| Decision | Pattern | Why |
|---|---|---|
| `include_tools=False` for per-item | LLM returns JSON directly | Cheaper — no tool-call roundtrip |
| `include_tools=True` for orchestrator | LLM calls tools to explore | Enables interactive exploration |
| `on_error="collect"` in fan_out | Partial success allowed | 1 failed agent ≠ abort everything |
| Shared `GraphBackbone` | All agents read/write same store | Cross-class context ("what related classes are there?") |
| `ContextAssembler` budget | `budget_tokens=1500` | Prevent prompt overload |
| Per-class `FakeLLMProvider` | Different response per item | Demo mode produces realistic-looking data |
| `AgentFactory` with shared OpenAI | Singleton provider | Thread-safe HTTP; avoids 88 separate auth handshakes |
| `FileCheckpointStore` in prod | JSON-on-disk | SIGKILL-safe resume; needs JSON-serializable outputs |
| `next_state=None` → terminal | `SummarizeState` | Engine detects terminal by checking `StateTransition.next_state` |

---

## Switching Between Demo and Production

```bash
# Demo mode — no API key, deterministic FakeLLMProvider per item
python -m examples.my_domain.main

# Production — OpenAI (gpt-4o-mini by default from YAML)
OPENAI_API_KEY=sk-... python -m examples.my_domain.main

# Analyse a specific directory
OPENAI_API_KEY=sk-... python -m examples.my_domain.main --source ./my_project/
```

The switch is in `AgentFactory.__post_init__`:
```python
api_key = os.getenv("OPENAI_API_KEY")
if api_key:
    self._shared_llm = OpenAIProvider(api_key=api_key)
# else: build_fake_llm(item) called per item in factory.build()
```

---

## Common Mistakes

| Mistake | Fix |
|---|---|
| `include_tools=True` but no tool loop in `_execute` | Either add ReAct loop or use `include_tools=False` for single-shot JSON |
| `StateTransition(next_state="done")` where `"done"` doesn't exist in `states` | Use `next_state=None` to signal terminal |
| `FileCheckpointStore` with non-JSON output (custom dataclass) | Add `__json__` / convert to dict in `StateTransition.output` |
| `AgentPool.fan_out` with `on_error="raise"` (default) | One agent failure aborts all; use `on_error="collect"` for parallel fan-out |
| PromptRegistry variable mismatch | YAML `{variable}` must exactly match kwargs in `build_request(..., variable=value)` |
| Shared mutable state across agents | Pass `ContextAssembler(shared_backbone)` — backbone is the shared store, assembler is per-agent |

---

## Checklist for a New Domain

```
[ ] ingestion.py    — typed domain dataclass + to_context_text() + ingester
[ ] prompts/v1.yaml — analyze_item + summarize prompts + tool schemas
[ ] tools.py        — async handler per tool, build_registry() factory
[ ] agents.py       — ItemAnalysisAgent + Orchestrator + DomainReport + AgentFactory
[ ] workflow.py     — IngestState + AnalyseState (backbone=field) + SummarizeState
[ ] main.py         — wire Workflow + WorkflowEngine + InMemoryCheckpointStore + print results

Demo mode works:
[ ] python -m examples.my_domain.main   → exits 0, prints report

Production works (if you have a key):
[ ] OPENAI_API_KEY=sk-... python -m examples.my_domain.main → exits 0

Optional additions:
[ ] verifiers.py    — add LLMJudgeVerifier / SchemaVerifier for output quality
[ ] Add VerifierPipeline in SummarizeState to validate LLM output before returning
```
