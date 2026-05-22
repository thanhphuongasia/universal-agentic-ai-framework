# Changelog

All notable changes to RYUU follow [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed — Phase 9.0d.2: Drop `RecallPipeline` from `RyuuHandler` default

`RyuuHandler` now uses **warm-start** (top-3 recent observations pre-injected) instead of the full recall pipeline (intent → expand → decompose → retrieve → RRF). Rationale:

`ryuu.Agent` runs a **ReAct loop** with `recall`/`remember`/`list_memories` tools (via `MemoryToolset`). The LLM naturally:
- Decomposes compound queries via parallel `tool_use` (e.g. "list todos AND create flashcards" → 2 tool calls)
- Retries with paraphrases when first retrieval misses
- Skips recall for chitchat (it just doesn't call the tool)

Pre-LLM preprocessing (RecallPipeline) was redundant on top of ReAct. Removed it from `RyuuHandler.__post_init__`. Bot now boots:

```
[ryuu-super] ReAct paradigm: no recall preprocessing. LLM drives via tools.
```

**Removed from `RyuuHandler`:**
- `recall_pipeline: RecallPipeline | None` field

**Added:**
- `warm_start_top_k: int = 3` — top-N recent observations pre-injected. Set to 0 to disable warm-start entirely (LLM calls recall when it decides).

**RecallPipeline itself stays in `ryuu_cognitive.recall`** — useful for non-agent / RAG / batch / cost-capped use cases where LLM cannot iterate. Just not default for agent handlers.

### Docs — Quickstart updated with "when to use RecallPipeline"

`docs/guides/quickstart/README.md` adds a new section before the Cookbook:
- Decision tree: ReAct agent → skip pipeline; non-iterating → use pipeline
- Why ReAct handles decomposition naturally
- Concrete code for both paradigms (agent + tools vs RAG single-shot)
- Use-case table (when each paradigm fits)

### Added — Phase 9.0d.1: `ryuu_cognitive.recall` — composable memory retrieval

Middleware/chain-style recall pipeline. Framework owns orchestration; consumer just plugs stages into a list. Adding new stages = define class implementing `IRecallStage` + insert into list. **Zero framework changes** when extending.

**New layout** (sibling to existing `strategies/`, `verifiers/`, `context/`):

```
packages/ryuu-cognitive/src/ryuu_cognitive/recall/
├── pipeline.py    RecallPipeline, RecallContext, IRecallStage, RecallResult
├── stages.py      6 built-in stages
└── builders.py    RecallPipelineBuilder (naive/with_expansion/full)
```

**Pipeline contract:**

```python
@runtime_checkable
class IRecallStage(Protocol):
    name: str
    async def execute(
        self, ctx: RecallContext, *, backbone: IKnowledgeBackbone,
    ) -> RecallContext: ...

@dataclass
class RecallPipeline:
    backbone: IKnowledgeBackbone
    stages: list[IRecallStage] = field(default_factory=list)
    async def recall(query, scope_key) -> RecallResult: ...
```

Stages run in order. Any stage can set `ctx.skipped=True` to short-circuit (e.g. `IntentFilterStage` skips for chitchat).

**6 built-in stages:**

| Stage | Purpose |
|-------|---------|
| `IntentFilterStage(analyzer)` | Skip pipeline for chitchat / commands (saves cost) |
| `ExpansionStage(expander)` | Generate query paraphrases |
| `DecompositionStage(decomposer)` | Break complex queries; gated by `intent.complexity` |
| `MultiQueryRetrievalStage(top_k)` | Fan-out queries against backbone, dedupe |
| `RRFusionStage(k=60)` | Reciprocal Rank Fusion across query result lists (standard from Cormack et al., used by Anthropic/Cohere) |
| `TokenBudgetStage(budget_tokens)` | Trim final list to fit prompt budget |

**3 builders for common compositions:**

```python
# Naive — just retrieve
RecallPipelineBuilder.naive(backbone)

# + paraphrases + RRF
RecallPipelineBuilder.with_expansion(backbone, expander=...)

# Full Option C — analyzer + expand + decompose + retrieve + RRF + budget
RecallPipelineBuilder.full(
    backbone, analyzer=..., expander=..., decomposer=...,
)
```

**Custom stage example** (open/closed — extend without modifying framework):

```python
class RedisCacheStage:
    name = "redis_cache"
    def __init__(self, redis_client):
        self.cache = redis_client
    async def execute(self, ctx, *, backbone):
        key = f"recall:{ctx.scope_key}:{hash(ctx.original_query)}"
        cached = await self.cache.get(key)
        if cached:
            ctx.fused_results = json.loads(cached)
            ctx.skipped = True
            ctx.skip_reason = "cache_hit"
        return ctx

pipeline.stages.insert(0, RedisCacheStage(my_redis))   # framework untouched
```

### Changed — `RyuuHandler` now uses `RecallPipeline` instead of inline `assemble_context()`

```python
RyuuHandler(
    memory_backbone=...,
    recall_pipeline=RecallPipelineBuilder.full(...),    # NEW — optional
    # Falls back to naive RecallPipeline if not provided
)
```

`main_ryuu.py` wires `RecallPipelineBuilder.full()` when `OPENAI_API_KEY` available — analyzer (skip chitchat) + LLM expander (3 paraphrases) + decomposer + RRF fusion + token budget. Naive fallback when offline.

### Added — Phase 9.0c: Auto-compaction in `RyuuHandler` + Telegram controls

`RyuuHandler` now wires `LLMCompactor` automatically when `compaction_provider` + `prompt_registry` are injected. Long conversations get summarized BEFORE each LLM call instead of dropping oldest turns FIFO.

**Auto-compaction flow:**

```
User sends msg
    ↓
handle(msg, session)
    ↓
estimate tokens in session.history (~40-50 per turn)
    ↓
if est_tokens >= compact_threshold_tokens (default 4000):
    ↓
    LLMCompactor.compact(history)
        - keep last 5 turns verbatim
        - summarize older N turns into 1 "[summary]" turn
        - session.history = [summary_turn, *last_5_turns]
    ↓
build prompt with compacted history + memory recall + new msg
    ↓
agent.run()
```

**New `RyuuHandler` constructor args:**

```python
RyuuHandler(
    memory_backbone=...,
    compaction_provider=OpenAIProvider(...),    # NEW — enables auto-compact
    prompt_registry=make_framework_registry(),   # NEW — provides compaction/v1.yaml
    compact_keep_recent=5,                       # NEW — turns preserved verbatim
)
```

If `compaction_provider` is None, auto-compact is silently a no-op (LLMCompactor unbuilt). `RyuuHandler` works without it; users get FIFO history truncation.

**New per-scope settings** (persisted in handler_state):

| Field | Default | Purpose |
|-------|---------|---------|
| `auto_compact` | `True` | Toggle auto-trigger |
| `compact_threshold_tokens` | `4000` | When estimated tokens exceed, compact |

**New `RyuuHandler` methods:**

- `await handler.set_auto_compact(scope_key, on: bool)` — toggle
- `await handler.set_compact_threshold(scope_key, threshold: int)` — bounds: 500-100,000
- `await handler.manual_compact(scope_key, session)` — force compact NOW; returns `{before, after, saved_turns}`

**New Telegram commands** (via `TelegramAdapter.on_compact` + `on_auto_compact` callbacks):

```
/compact                  Force compaction NOW. Shows "60 turns → 6 turns (saved 54)"
/auto_compact             Show current state (on/off, threshold)
/auto_compact on          Enable auto-trigger
/auto_compact off         Disable — bot still keeps full history; use /compact manually
```

**TelegramAdapter API additions:**

```python
TelegramAdapter(
    ...,
    on_compact: AsyncCallable[[sender_id, conv_id], str] = None,
    on_auto_compact: AsyncCallable[[sender_id, conv_id, on: bool|None], str] = None,
)
```

Updated `DEFAULT_HELP` text to document the 2 new commands.

### Added — Phase 9.0b: `MemoryToolset` in `ryuu-knowledge-memory`

Pre-built memory tools (remember/recall/list_memories + opt-in forget) with internal scope binding. Consumer code shrinks from ~120 LOC boilerplate to ~3 LOC.

**Public API:**

```python
from ryuu_knowledge_memory import MemoryToolset

toolset = MemoryToolset(backbone=my_backbone)
agent = Agent(tools=toolset.tools, ...)

async with toolset.bind(scope_key="owner"):
    result = await agent.run(message=prompt)
```

**Default tools** (all safe — read or append-only):
- `remember(fact)` — INSERT
- `recall(query)` — SELECT (keyword overlap)
- `list_memories()` — SELECT recent N

**Opt-in tool** (destructive — requires explicit consent):
- `forget(query)` — DELETE; pass `include_forget=True` to enable

```python
# Default — 3 safe tools, no forget
MemoryToolset(backbone=bb)

# With destructive tool — explicit opt-in
MemoryToolset(backbone=bb, include_forget=True)

# Custom subset (e.g. read-only consumer)
MemoryToolset(backbone=bb, tool_names=("recall",))
```

**Per-instance contextvar** — multiple `MemoryToolset`s in the same process don't collide. Each has its own `_scope_var` for clean isolation.

**Design rationale:** framework ships PRIMITIVES (tools + binder), product owns POLICY (when/what to write, where to inject recall). Auto-write-every-message and auto-extract-via-LLM were considered and rejected (noise + 2x cost respectively).

### Changed — `RyuuHandler` refactored to use `MemoryToolset`

Sample's `examples/ryuu_sensei/apps/ryuu_tools.py` (~120 LOC of contextvar plumbing + tool definitions) **deleted**. Replaced by 3 lines in `RyuuHandler.__post_init__`:

```python
def __post_init__(self):
    if self.memory_backbone is not None:
        self._toolset = MemoryToolset(
            backbone=self.memory_backbone,
            include_forget=self.include_forget_tool,
        )
```

Per-turn binding via `async with`:
```python
async with self._toolset.bind(scope_key=session.scope_key):
    result = await agent.run(message=prompt_text, ...)
```

### Changed — Phase 8.13–8.19: Standalone package extractions (5 phases)

Continuing Phase 8.x reorganization. **All old imports preserved via shims.**

#### Phase 8.13 — Split `ryuu-observability` into core + OTel adapter

| New package | Contents | External deps |
|---|---|---|
| `ryuu-observability-core` | `CostTracker`, `AuditLogger` (JSONL hash chain), `RateLimiter` — in-process primitives | none |
| `ryuu-observability-otel` | `Tracer`, `setup_tracing` (OTLP/Jaeger/Tempo) | `opentelemetry-api>=1.20`, `opentelemetry-sdk>=1.20` |

`ryuu-observability` becomes back-compat metapackage with `[otel]` extra.

```python
# Old (still works):
from ryuu_observability import CostTracker, Tracer

# New (no OTel pull-in for in-process-only use):
from ryuu_observability_core import CostTracker
from ryuu_observability_otel import Tracer    # only if needed
```

#### Phase 8.14 — `LLMIntentAnalyzer` moved to `ryuu-intent`

`ryuu-intent` now owns the FULL intent classification surface (difficulty + analyzer). Symmetric with prompt YAMLs co-located:

| Moved from | To |
|---|---|
| `ryuu_runtime.llm_analyzer.LLMIntentAnalyzer` | `ryuu_intent.llm_analyzer.LLMIntentAnalyzer` |
| `ryuu_runtime/prompts/intent/v1.yaml` | `ryuu_intent/prompts/intent/v1.yaml` |

Shim at `ryuu_runtime.llm_analyzer` re-exports — old imports keep working. `ryuu-intent` now depends on `ryuu-providers-core`.

#### Phase 8.15 — Split `ryuu-eval` into core + scorers

| New package | Contents |
|---|---|
| `ryuu-eval-core` | `EvalRunner`, `EvalCase`, `Scorer` Protocol, `EvalTarget` Protocol, `FixtureLoader`, renderers |
| `ryuu-eval-scorers` | Default scorers: `ExactMatch`, `Constraint`, `Threshold`, `Composite`, `LLMJudge` |

`ryuu-eval` becomes back-compat metapackage depending on both. Lets product teams ship custom scorers without bundling framework defaults.

#### Phase 8.17 — DEFERRED

`PromptOptimizer` extraction was attempted but reverted. Reason: tightly coupled to umbrella's `ryuu.factory.Agent` (mutates internal `_FactoryLLMAgent.system_prompt`). Requires refactor to Protocol-based agent before clean extraction. Tracked for future work.

#### Phase 8.18 — Extract `ryuu/hooks.py` → `ryuu-hooks`

Hook system (PRE_LLM, POST_LLM, ON_ERROR, …) — 272 LOC, clean deps (only `ryuu-core` + `ryuu-workflow`). Now standalone for product teams that want lifecycle injection without pulling the umbrella.

```python
# Old (shim works):
from ryuu.hooks import HookEvent, HookRegistry

# New:
from ryuu_hooks import HookEvent, HookRegistry
```

#### Phase 8.19 — Factory audit (no changes)

`ryuu/factory/` audited for cleanup opportunities. Verdict: **stays in umbrella as-is.** It's the public convenience facade composing `ryuu-execution`, `ryuu-providers-core`, `ryuu-hooks`, `ryuu-prompts`. Splitting would force users into lower-level APIs without ergonomic gain. No dead code, no TODOs, no smell.

---

### Changed — Phase 8.12: Split `ryuu-providers` into core + adapter packages

`ryuu-providers` split into 3 sub-packages so users only install the SDK they need. **All old imports continue to work via back-compat shims** — no breaking change.

**New packages:**

| Package | Contents | External deps |
|---------|----------|---------------|
| `ryuu-providers-core` | `ILLMProvider` Protocol, value types (`CompletionRequest`, `Message`, `Response`, `TokenUsage`, `Embedding`), pricing (`calculate_usd`, `PRICING`, `pricing.yaml`), middleware (`CircuitBreaker`, `ModelRouter`, `ProviderFallbackChain`) | `pyyaml` only |
| `ryuu-providers-openai` | `OpenAIProvider` adapter | `ryuu-providers-core` + `openai>=1.0` |
| `ryuu-providers-anthropic` | `AnthropicProvider` adapter | `ryuu-providers-core` + `anthropic>=0.30` |

**Original `ryuu-providers`** becomes a thin back-compat metapackage:
- `pyproject.toml` depends on `ryuu-providers-core`; extras `[openai]`, `[anthropic]`, `[all]` pull in adapter sub-packages
- Source files are now shims re-exporting from the new packages

**Install patterns:**

```bash
# Old (still works):
pip install 'ryuu-providers[openai]'         # → core + openai adapter

# New (recommended for fine-grained):
pip install ryuu-providers-openai            # → just OpenAI + core; never pulls anthropic
pip install ryuu-providers-anthropic         # → just Anthropic + core
pip install ryuu-providers-core              # → only Protocols, types, pricing, middleware
```

**Import patterns:**

```python
# Old (back-compat shims — keep working):
from ryuu_providers.llm import ILLMProvider, CompletionRequest
from ryuu_providers.adapters.openai import OpenAIProvider
from ryuu_providers.adapters.anthropic import AnthropicProvider
from ryuu_providers._pricing import calculate_usd
from ryuu_providers.router import ModelRouter

# New (preferred — direct, no shim):
from ryuu_providers_core import ILLMProvider, CompletionRequest, ModelRouter, calculate_usd
from ryuu_providers_openai import OpenAIProvider
from ryuu_providers_anthropic import AnthropicProvider
```

Protocol identity is preserved (`ryuu_providers.llm.ILLMProvider is ryuu_providers_core.llm.ILLMProvider`) — code that does `isinstance(p, ILLMProvider)` works identically across both import paths.

### Changed — Phase 8.11: Move providers + observability into `infrastructure/`

Continuing Phase 8.10 architecture cleanup. **Import paths unchanged** — no code or back-compat shims required, only filesystem layout.

| From | To |
|------|-----|
| `packages/ryuu-providers/` | `packages/infrastructure/providers/ryuu-providers/` |
| `packages/ryuu-observability/` | `packages/infrastructure/observability/ryuu-observability/` |

**Top-level `packages/` after Phase 8.11 contains ONLY Domain + Use Case layers (11 packages):**

```
packages/
├── ryuu-core/                       Domain — pure types
├── ryuu-workflow/                   Use Case — workflow engine
├── ryuu-guardrail/                  Use Case — policy
├── ryuu-cognitive/                  Use Cases — strategies, verifiers, context
├── ryuu-execution/                  Use Case — agent + tool registry
├── ryuu-knowledge-base/             Use Case — IKnowledgeBackbone Protocol
├── ryuu-runtime/                    Use Case — orchestration
├── ryuu-reasoning/                  Use Case — formal verifiers
├── ryuu-intent/                     Use Case — difficulty classification
├── ryuu-prompts/                    Use Case — versioned prompt management
├── ryuu-eval/                       Dev tools
└── infrastructure/                  Adapters to external systems
    ├── providers/                   LLM API adapters (openai, anthropic, fake)
    ├── observability/               cost/audit/trace exporters
    ├── messaging/                   channel transport (telegram, cli)
    ├── storage/                     KV/Collection backends (sqlite, jsonl, memory)
    └── knowledge-impls/             concrete memory/graph/rag backbones
```

**Files updated:** `scripts/install-dev.sh`, 6 isolation scripts (cognitive, runtime, providers, eval, execution, observability), `.github/workflows/ci.yml` (13 path refs).

### Changed — Phase 8.10: Clean Architecture folder reorganization

7 packages moved into `packages/infrastructure/` to match Clean Architecture vertical slicing. **Import paths unchanged** — `from ryuu_knowledge_memory import …` etc. continue to work. Only the filesystem layout changed.

**Folder moves:**

| From | To |
|------|-----|
| `packages/messaging/ryuu-messaging-{core,cli,telegram}/` | `packages/infrastructure/messaging/ryuu-messaging-{core,cli,telegram}/` |
| `packages/ryuu-knowledge-memory/` | `packages/infrastructure/knowledge-impls/ryuu-knowledge-memory/` |
| `packages/ryuu-knowledge-graph/` | `packages/infrastructure/knowledge-impls/ryuu-knowledge-graph/` |
| `packages/ryuu-knowledge-rag/` | `packages/infrastructure/knowledge-impls/ryuu-knowledge-rag/` |
| `packages/ryuu-knowledge/` (hybrid) | `packages/infrastructure/knowledge-impls/ryuu-knowledge/` |

**Top-level `packages/` after Phase 8.10 contains only Domain + Use Case layers:**

```
packages/
├── ryuu-core/                       Domain — pure types
├── ryuu-workflow/                   Use Case — workflow engine
├── ryuu-providers/                  (LLM provider — TBD move in Phase 8.11)
├── ryuu-observability/              (cost/audit/trace — TBD move in Phase 8.11)
├── ryuu-guardrail/                  Use Case — policy
├── ryuu-cognitive/                  Use Cases — strategies, verifiers, context
├── ryuu-execution/                  Use Case — agent + tool registry
├── ryuu-knowledge-base/             Use Case — IKnowledgeBackbone Protocol
├── ryuu-runtime/                    Use Case — orchestration
├── ryuu-reasoning/                  Use Case — formal verifiers
├── ryuu-intent/                     Use Case — difficulty classification
├── ryuu-prompts/                    Use Case — versioned prompt management
├── ryuu-eval/                       Dev tools
└── infrastructure/                  Adapters to external systems
    ├── messaging/                   Channel transport (telegram, cli, slack, …)
    ├── storage/                     KV/Collection backends (sqlite, jsonl, memory, …)
    └── knowledge-impls/             Concrete memory/graph/rag backbones
```

**CI workflow + isolation scripts updated** — `.github/workflows/ci.yml` and `scripts/test-knowledge-isolation.sh` reference new paths.

**No back-compat shims required** — packages preserve their distribution names (`ryuu-knowledge-memory`, `ryuu-messaging-telegram`, etc.) and import paths (`from ryuu_knowledge_memory import …`).

### Added — Phase 8.9.E: `ryuu-prompts` + `ryuu-intent` standalone packages

Two new standalone packages extracted from the umbrella `ryuu/` namespace.
Standalone packages can now consume prompt management + difficulty
classification without depending on the umbrella facade.

**`ryuu-prompts`** (Tier 2.5 — depends on `ryuu-providers`):
- `PromptRegistry` (moved from `ryuu/prompts/registry.py`)
- `PromptConfig`, `PromptTemplate`, `ToolDefinition` (moved from `ryuu/prompts/models.py`)
- **NEW:** Multi-root layered overlay — `PromptRegistry(prompts_roots=[user_dir, default_dir])`. First match wins.
- **NEW:** `make_framework_registry()` factory auto-discovers all installed `ryuu-*` package prompts.
- **NEW:** `package_default_root(pkg_name)` helper.

**`ryuu-intent`** (Tier 1 — zero deps):
- `Difficulty`, `normalize_difficulty()`, `DEFAULT_PROMPT` (moved from `ryuu/_difficulty_classifier.py`).
- Ships YAML at `ryuu_intent/prompts/difficulty/v1.yaml`.

### Changed — Inline prompts externalized to per-package YAML

6 inline `*_PROMPT` constants converted to YAML files alongside owning packages, loaded via `PromptRegistry`. Editing YAML now takes effect on next process start — no code redeploy.

| Was in | YAML now lives at |
|--------|-------------------|
| `ryuu_cognitive/context/compaction.py` (`DEFAULT_COMPACT_PROMPT`) | `ryuu_cognitive/prompts/compaction/v1.yaml` |
| `ryuu_cognitive/context/query_expansion.py` (`DEFAULT_EXPAND_PROMPT`) | `ryuu_cognitive/prompts/query_expansion/v1.yaml` |
| `ryuu_cognitive/context/query_decomposition.py` (`DEFAULT_DECOMPOSE_PROMPT`) | `ryuu_cognitive/prompts/query_decomposition/v1.yaml` |
| `ryuu_cognitive/verifiers/llm_judge.py` (`_JUDGE_PROMPT`) | `ryuu_cognitive/prompts/judge/v1.yaml` |
| `ryuu_runtime/llm_analyzer.py` (`INTENT_SYSTEM_PROMPT`) | `ryuu_runtime/prompts/intent/v1.yaml` |
| `ryuu/_difficulty_classifier.py` (`DEFAULT_PROMPT`) | `ryuu_intent/prompts/difficulty/v1.yaml` |

### Changed — context primitive API (breaking, with shims)

`LLMCompactor` / `LLMQueryExpander` / `LLMQueryDecomposer` now take `ILLMProvider + PromptRegistry` instead of a raw `LLMCallable`:

```python
# Before (Phase 8.9 — removed):
LLMCompactor(llm=my_callable_fn, prompt_template="...")

# After (Phase 8.9.E):
from ryuu_prompts import make_framework_registry
from ryuu_providers.adapters.openai import OpenAIProvider

registry = make_framework_registry()
provider = OpenAIProvider(api_key=...)
LLMCompactor(provider=provider, registry=registry)
```

Non-LLM fallbacks (`SynonymExpander`, `PatternQueryDecomposer`) unchanged.

### Fixed — `TodoHandler.reset_scope` (sample) didn't persist clear

`/clear` left stale stats in SQLite — a restart between `/clear` and the next message would resurrect old stats. `reset_scope` is now async, evicts the load-once cache, and writes the blank state through.

### Backward compatibility

All old imports continue to work via shims:

```python
from ryuu.prompts import PromptRegistry           # → ryuu_prompts (works)
from ryuu.prompts.registry import PromptRegistry  # → ryuu_prompts.registry (works)
from ryuu.prompts.models import PromptConfig      # → ryuu_prompts.models (works)
from ryuu._difficulty_classifier import normalize_difficulty  # → ryuu_intent (works)
```

New code should prefer `from ryuu_prompts import ...` and `from ryuu_intent import ...`.

## [0.3.0a17] - 2026-05-22

### Added — Phase 11.z: `NeighborGraphBackbone` in `ryuu-knowledge-graph`

New `IKnowledgeBackbone` variant — neighbor-expansion mode over `IGraphStore`.
Complements existing `GraphBackbone` (text_search mode):

  | Backbone               | query() semantic                      |
  |------------------------|---------------------------------------|
  | GraphBackbone          | text_search(query) — semantic match    |
  | NeighborGraphBackbone  | get_neighbors(entity_id) — graph expand|

**Usage:**

```python
from ryuu_knowledge_graph import NeighborGraphBackbone, InMemoryGraphStore

backbone = NeighborGraphBackbone(
    store=neo4j_store,           # any IGraphStore impl
    max_hops=1,
    formatter=domain_formatter,   # optional — domain-specific text render
)
ctx = await backbone.assemble_context(
    query="UserController",       # known entity_id
    scope_key="my-project",
    budget_tokens=500,
)
# ctx.text contains node + 1-hop neighbors formatted as text
```

**Use cases (pattern):**
- Code analysis — class + dependencies/dependents as ReAct context
- Knowledge graphs — entity + related concepts
- Social networks — author + co-authors/followers
- Citation networks — paper + cited/cited-by
- Recommendation — product + bought-together items

**Design notes:**
- 3-layer architecture: Framework (Protocol + Backbone) — Infrastructure
  (Neo4j/Memgraph adapters in app code) — Domain (formatter in app code).
  ryuu doesn't bundle DB-specific drivers.
- `max_hops=1` default; raises ValueError if < 1.
- `formatter=` callable for domain rendering; default = labels + properties.
- Budget enforcement: trim neighbors BFS-first until fits token budget.
- `write()` adds isolated observation node (caller wires edges via IGraphStore).

**Tests:** +13 (construction, query with known/unknown entity, max_hops scaling,
top_k, assemble with budget trimming, custom formatter, write observation).
Total: 1016 passed, 7 skipped, 0 regression.

**Public API exports** (from `ryuu_knowledge_graph`):
- `NeighborGraphBackbone` (new)
- `GraphBackbone` (existing)
- `InMemoryGraphStore`, `IGraphStore`, `Node`, `Edge` (existing)

## [0.3.0a16] - 2026-05-22

### Added — Phase 14.7: `ryuu-reasoning` MVP — formal verifiers

New standalone package providing formal verifiers for the cognitive verifier
pipeline. Pure Python `RuleVerifier` (no deps) + optional `Z3Verifier` (SMT).

**Public API:**

```python
from ryuu_reasoning import Rule, RuleVerifier, Z3Verifier

# Rule-based (no deps)
verifier = RuleVerifier(rules=[
    Rule(name="positive", expression="amount > 0", severity="critical"),
    Rule(name="ratio", expression="amount <= 0.3 * income", severity="critical"),
    Rule(name="prefer", expression="amount <= 50000", severity="warning"),
])

# Z3 SMT (optional: pip install "ryuu-reasoning[z3]")
def loan(data, z3):
    return z3.And(data["amount"] <= 0.3 * data["income"], data["amount"] <= 100000)

verifier = Z3Verifier(constraint_builder=loan)
```

**Components:**
- `Rule` — predicate (Callable) OR expression (string eval'd safely with no
  builtins). Severity `critical` fails verification; `warning` informs only.
- `RuleVerifier` — IVerifier impl. Parses LLM output as JSON, evaluates rules
  against dict, returns `VerificationResult(passed, confidence, feedback)`.
- `Z3Verifier` — IVerifier impl wrapping z3-solver. `constraint_builder(data, z3)`
  returns z3 BoolRef; verifier checks satisfiability. Raises ImportError if
  z3-solver not installed.

**Use case matrix:**

| Need | Use |
|---|---|
| Predicate rules (field comparisons) | `RuleVerifier` |
| Arithmetic constraints (LP, ILP) | `Z3Verifier` |
| Logical chains, knowledge base | PrologVerifier (future Phase 14.7.x) |
| Pattern queries over large facts | SouffleVerifier (future) |

**Integration:** plug as `IVerifier` in `VerifierPipeline`:
```
SchemaVerifier → LLMJudgeVerifier → GroundTruthVerifier →
  RuleVerifier (compliance) → Z3Verifier (constraints)
```

**Tests:** +9 RuleVerifier + 4 Z3Verifier (skipped if z3-solver not installed).
Total: 1003 passed, 7 skipped (+4 new Z3 + 3 existing). 0 regression.

**Example:** `examples/reasoning_demo.py` — 3 loan compliance scenarios with
RuleVerifier + Z3 SMT-backed validation.

**Installer:** `scripts/install-dev.sh` adds `ryuu-reasoning` in Tier 4.

## [0.3.0a15] - 2026-05-22

### Added — Phase 11.y: Factory `output_schema=` + OpenAI strict JSON Schema mode

Expose existing provider-layer structured output support through the Factory
ergonomic kwarg, and upgrade OpenAI adapter to use modern strict JSON Schema
mode (gpt-4o+) instead of basic json_object fallback.

**New Agent kwarg:**

```python
agent = Agent(
    model="gpt-4o-mini",
    instructions="Extract person info from text",
    output_schema={                              # ← NEW
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
        },
        "required": ["name"],
        "additionalProperties": False,
    },
)
result = await agent.run("Alice is 30 years old")
print(result.output)   # Raw JSON string: '{"name":"Alice","age":30}'
print(result.parsed)   # Auto-parsed dict: {"name": "Alice", "age": 30}
```

**New AgentResult field:**
- `parsed: Any = None` — populated với `json.loads(output)` when `output_schema`
  set and parse succeeds. Strips ```json fences if model wraps output.
  Backward-compat default None.

**OpenAI adapter upgrade:**
- Detect gpt-4o family / o1 / o3 / o4 / gpt-5 → strict mode:
  `response_format={"type": "json_schema", "json_schema": {..., "strict": True}}`
- Older models (gpt-3.5, gpt-4 base) → fallback to basic `json_object`.
- Helper: `_supports_strict_schema(model: str) -> bool` (exposed for testing).

**Anthropic adapter:** No change — already used tool-use trick for strict
schema enforcement.

**Internal flow per .run():**
1. Factory forwards `output_schema` → `_FactoryLLMAgent._output_schema` field
2. `_run_inner` passes to `CompletionRequest(response_schema=...)`
3. Provider serializes per its API (strict vs basic vs tool-use)
4. After LLM returns: best-effort `json.loads()` → `AgentResult.parsed`
5. Parse fail → `parsed=None`, raw text still in `output` (graceful)

**Tests:** +7 (auto-parse / strip markdown fences / invalid JSON graceful / no
schema → parsed=None / forwarding / OpenAI strict mode detection / kwargs build).
Total: 994 passed, 3 skipped, 0 regression from 0.3.0a14.

## [0.3.0a14] - 2026-05-22

### Added — Phase 11.x: Factory `knowledge=` integration

Wire `RAGBackbone` (or any `IKnowledgeBackbone`) into `Agent()` factory for
automatic RAG context injection on every `.run()` call.

**New Agent kwargs:**

```python
agent = Agent(
    model="gpt-4o-mini",
    instructions="Answer based on retrieved context",
    knowledge=backbone,                          # IKnowledgeBackbone instance
    knowledge_budget_tokens=2000,                # max context tokens (default 2000)
    knowledge_scope_field="domain",              # "user_id"|"session_id"|"domain"
)
result = await agent.run("question", domain="engineering")
```

**Internal flow per `.run()`:**

1. Resolve user_content (Mode 1 message OR Mode 2 user_template).
2. If `knowledge is not None`:
   - `scope_key = getattr(scope, knowledge_scope_field, "default")`
   - `assembled = await knowledge.assemble_context(query, scope_key, budget)`
   - If `assembled.text` non-empty: prepend `"Context (retrieved knowledge):\n{text}\n---\nQuery:\n{original}"`
3. Continue normal dispatch (compatible với thinking_mode, n_samples, adaptive_compute).

**Backward compat:** `knowledge=None` (default) → no injection, user_content unchanged.
**Scope isolation:** different `domain=` per `.run()` → different scope_key → different retrieved set.

**Tests:** +5 (prepend / no-injection default / scope filtering / budget respected / empty backbone graceful).

**Example:** `examples/rag_agent_demo.py` — Agent + RAGBackbone end-to-end với company docs + scope isolation demo.

## [0.3.0a13] - 2026-05-22

### Added — Phase 11: `ryuu-knowledge-rag` MVP

New standalone package `packages/ryuu-knowledge-rag/` providing RAG pipeline
components (chunker + vector store + retriever + IKnowledgeBackbone impl).

**Public API:**

```python
from ryuu_knowledge_rag import (
    Chunk, IChunker, RecursiveChunker,          # chunking
    VectorRecord, SearchResult, IVectorStore, InMemoryVectorStore,   # vector storage
    IRetriever, DenseRetriever,                  # retrieval
    RAGPipeline,                                  # end-to-end ingest + retrieve
    RAGBackbone,                                  # IKnowledgeBackbone impl
)
```

**Components:**
- `RecursiveChunker` — character-count splitting with overlap, walks natural
  boundaries (`\n\n` > `\n` > `". "` > `" "`). Default chunk_size=1500, overlap=200.
- `InMemoryVectorStore` — numpy-backed cosine similarity search with metadata
  filtering. Lazy L2-normalization (rebuild matrix on dirty flag). Production:
  swap for Chroma/Qdrant/Pinecone via same `IVectorStore` Protocol.
- `DenseRetriever` — embed query + cosine top-k via vector store.
- `RAGPipeline` — chunk + embed + upsert (`ingest`); retrieve (semantic search
  with scope filtering). Accepts list of strings OR dicts with `text` + `metadata`.
- `RAGBackbone` — `IKnowledgeBackbone` impl wrapping RAGPipeline. Implements
  `write` / `query` / `assemble_context` with `budget_tokens` trimming. Pluggable
  into Factory `knowledge=` param (integration deferred to Phase 11.x).

**Tests:** +17 (4 chunker + 5 vector store + 5 pipeline + 3 backbone).

**Example:** `examples/rag_demo.py` — ingest 6 docs → semantic queries →
assemble context with budget enforcement.

**Installer:** `scripts/install-dev.sh` updated with `ryuu-knowledge-rag` in
Tier 4 (depends on tier 3+).

## [0.3.0a12] - 2026-05-21

### Added — Phase 14.1-14.4: Claude-like Thinking Patterns (2-layer architecture)

**Layer A (mechanism)** — 3 cognitive strategies trong `ryuu-cognitive/strategies/`:

```python
from ryuu_cognitive.strategies import (
    ThinkingStrategy,    # <thinking>/<answer> wrap (Phase 14.1)
    BestOfNStrategy,     # sample N + vote (Phase 14.2)
    AdaptiveStrategy,    # difficulty → tier dispatch (Phase 14.3)
)
```

Each `ICognitiveStrategy` impl usable directly với class-based BaseAgent.

**Layer B (ergonomic)** — Factory kwargs convenience + `strategy=` explicit:

```python
# Kwargs (90% use case)
Agent(model="gpt-4o", thinking_mode=True)                         # → ThinkingStrategy
Agent(model="gpt-4o", n_samples=3, vote="majority")                # → BestOfNStrategy
Agent(model="gpt-4o", adaptive_compute=True, tier_models={...})    # → AdaptiveStrategy

# Explicit (advanced, mutually exclusive với kwargs)
Agent(model="gpt-4o", strategy=BestOfNStrategy(n=5, vote="llm_judge"))
```

**Phase 14.4 — `HierarchicalRouter` facade** (routing, không phải cognitive):

```python
from ryuu import HierarchicalRouter

router = HierarchicalRouter(
    category_classifier=Agent(model="gpt-4o-mini", instructions="..."),
    routes_by_category={"data": {"crud_matrix": agent_a}, "structure": {...}},
    fallback_route=default_agent,
    specific_analyzer=lambda q, opts: opts[0],   # optional custom Stage 2
)
result = await router.run(query)
```

**New API surface:**
- `Agent` kwargs: `thinking_mode`, `n_samples`, `vote`, `confidence_threshold`,
  `score_fn`, `adaptive_compute`, `tier_models`, `tier_max_iterations`,
  `tier_max_tokens`, `strategy`
- `AgentResult.thinking: str = ""` (Phase 14.1 parsed reasoning, backward-compat default)
- `ryuu_cognitive.strategies.ThinkingStrategy` / `BestOfNStrategy` / `AdaptiveStrategy`
- `ryuu.HierarchicalRouter` facade (re-exported from top-level)
- `ryuu._thinking_parser` / `ryuu._difficulty_classifier` helpers

**Validation:** kwargs (`thinking_mode` / `n_samples > 1` / `adaptive_compute`) mutually
exclusive với `strategy=` explicit → ValueError.

**Tests:** +34 (10 thinking + 10 best_of_n + 9 adaptive + 5 hierarchical_router).

### Changed — Modular refactor: factory.py + facades.py → packages

`ryuu/factory.py` (1005 lines) → `ryuu/factory/` package (6 files, all < 500 lines):
- `__init__.py` (28) — re-export Agent + StreamEvent
- `stream_event.py` (34) — StreamEvent + RESERVED_SCOPE_KEYS
- `_internal_agent.py` (242) — `_FactoryLLMAgent` (LLMAgent subclass)
- `_resolvers.py` (148) — `validate`, `resolve_file_paths`, `resolve_yaml_prompt`
- `_builders.py` (192) — `build_tool_registry`, `build_hook_registry`, `build_cross_cutting`, `apply_yaml_tool_schemas`, `wrap_tool_registry_with_hooks`
- `agent.py` (481) — Agent class + `__post_init__` + `run` + `stream` + `_run_*`

`ryuu/facades.py` (348 lines) → `ryuu/facades/` package (8 files):
- `__init__.py` — re-exports
- `_helpers.py` — shared `run_step`
- One file per facade class (chain / fanout / router / orchestrator / evaluator / hierarchical_router)

Public API unchanged. `from ryuu import Agent, Chain, ...` continues working.

### Docs

- `tasks/plan-phase14-thinking-patterns.md` — detailed 2-layer plan
- `tasks/roadmap-phase8.8-to-14.md` — Phase 14.1-14.6 sub-phases + Phase 14.7 reasoning
- `docs/architecture/uaaf-v2-architecture.md` — §7 Cognitive Tier updated với 3 new strategies
- `examples/code_analysis/docs/2026-05-21_migration-to-ryuu.md` — §16 Thinking Patterns
- `examples/code_analysis/intent_patterns_demo.py` — side-by-side self-impl vs built-in
- `examples/todo_app/factory_demo.py` — Factory + facade demo

### Tests

965 unit + 7 perf + 3 integration (no regression from 0.3.0a11 → +34 new tests).

## [0.3.0a11] - 2026-05-21

### Added — Phase 12.1: Real OpenAI Batch API implementation

`BatchRunner(mode="openai_batch")` no longer stubs — implements full flow:

```python
from ryuu import Agent, BatchRunner, OpenAIBatchClient

agent = Agent(model="gpt-4o-mini", instructions="Summarize")
runner = BatchRunner(
    agent=agent,
    mode="openai_batch",
    poll_interval_s=30.0,        # poll cadence
    completion_window="24h",     # OpenAI SLA window
)

# 1000 inputs at 50% cost discount (24h SLA, usually <1h actual)
results = await runner.run([{"id": f"doc-{i}", "input": text} for i, text in enumerate(corpus)])
# Returns list[BatchItem(id, output, error?)] in input order
```

**Flow:**
1. Build JSONL: one chat completion request per input (model + system + user msg)
2. Upload via Files API (`purpose="batch"`) → input_file_id
3. Create batch (`endpoint="/v1/chat/completions"`, `completion_window="24h"`) → batch_id
4. Poll status every `poll_interval_s` until terminal state
5. On `completed` → download output JSONL → parse line-by-line
6. Map `custom_id` back to input index → results in original order

**Error handling:**
- Batch status `failed/expired/cancelled` → `RuntimeError` with batch_id + error_file_id
- Individual line errors (rate limit, etc.) → `BatchItem.error` set; `on_error="raise"` propagates, `"collect"` continues

**New public types:**
- `BatchAPIClient` Protocol — abstraction for tests/custom impls
- `OpenAIBatchClient` — production impl using `AsyncOpenAI` SDK
  - Lazy import of openai SDK (only when instantiated)
- `BatchRunner.batch_client: BatchAPIClient | None` — inject custom (e.g. fake for tests)
- `BatchRunner.poll_interval_s: float = 30.0`
- `BatchRunner.completion_window: str = "24h"`
- `BatchRunner.batch_endpoint: str = "/v1/chat/completions"`

**Cost benefit:** OpenAI Batch API charges 50% of standard rate for both input
and output tokens. Use when:
- You have ≥ 100 inputs and don't need real-time response
- Workload tolerates 24h SLA (vast majority complete < 1h)

**Tests:** +7 unit using `FakeBatchAPIClient` (no network). 930 total.

## [0.3.0a10] - 2026-05-21

### Added — Phase 13: PromptOptimizer (auto-tune prompts via eval loop)

`ryuu.prompt_optimizer.PromptOptimizer` — auto-tune prompts by evaluating
variants against eval cases. Inspired by DSPy + OpenAI Prompt Optimizer.

```python
from ryuu import Agent, EvalCase, PromptOptimizer
from ryuu.prompt_optimizer import llm_variant_generator

cases = [
    EvalCase(input="What is 2+2?", expected="4"),
    EvalCase(input="What is 10*5?", expected="50"),
]

base = Agent(model="gpt-4o-mini", instructions="You are a math tutor")
optimizer = PromptOptimizer(
    base_agent=base,
    eval_cases=cases,
    score_fn=lambda out, exp: 1.0 if exp in out else 0.0,
    variant_generator=llm_variant_generator(provider=base._agent.llm, n_variants=3),
    max_rounds=3,
)
result = await optimizer.optimize()
print(f"Best prompt: {result.best_prompt} (score {result.best_score:.2f})")
print(f"History: {len(result.history)} evaluations across {result.rounds_completed} rounds")
```

**Algorithm:** Greedy hill climb — each round generates N variants, picks
highest-scoring, uses it as base for next round.

**New API:**
- `EvalCase(input, expected)` — single eval case
- `PromptOptimizer(base_agent, eval_cases, score_fn, variant_generator, max_rounds)`
- `OptimizationResult(best_prompt, best_score, history, rounds_completed)`
- `llm_variant_generator(provider, n_variants=3, model=...)` — built-in paraphrase
  generator. Parses LLM output, strips numbered/bulleted prefixes.

**Variant generator contract:** `Callable[[current_prompt: str], list[str] | Awaitable[list[str]]]`
— sync or async, user-supplied or built-in.

**Score function contract:** `Callable[[output: str, expected: str], float | Awaitable[float]]`
— return 0.0-1.0 (higher = better). Sync or async.

**Top-level exports:** `from ryuu import EvalCase, PromptOptimizer, OptimizationResult`

**Tests:** +8 unit (923 total).

## [0.3.0a9] - 2026-05-21

### Added — Phase 12: BatchRunner for processing N inputs

`ryuu.batch.BatchRunner` — process list of inputs through an Agent in batch.
Two modes:

```python
from ryuu import Agent, BatchRunner

agent = Agent(model="gpt-4o-mini", instructions="Summarize")

# Mode: gather (default) — concurrent via anyio task group + semaphore
runner = BatchRunner(agent=agent, max_concurrent=10)
results = await runner.run(["Text 1", "Text 2", "Text 3"])

# With custom IDs — returns list[BatchItem] preserving id
results = await runner.run([
    {"id": "doc-1", "input": "Text 1"},
    {"id": "doc-2", "input": "Text 2"},
])
# results[0].id == "doc-1", .output, .cost_usd
```

**Modes:**
- `gather` (✅ shipped) — concurrent execution, works with any provider, no cost
  savings. `max_concurrent` caps parallelism via `anyio.Semaphore`.
- `openai_batch` (🔲 Phase 12.1 stub) — true OpenAI Batch API integration for
  50% discount + 24h SLA. Currently raises `NotImplementedError` with
  implementation TODO (submit JSONL, poll, parse).

**Error handling:**
- `on_error="raise"` (default) — first failure halts batch + propagates
- `on_error="collect"` — failed items return `BatchItem(error=exc)`, batch continues

**Top-level exports:** `from ryuu import BatchRunner, BatchItem`

**Tests:** +8 unit (914 total: 116 Factory + new 8 batch).

**See:** future `docs/guides/batch.md` for full guide.

## [0.3.0a8] - 2026-05-21

### Performance — Phase 9.3: Fix sync I/O hotspots identified in 8.8 audit

**Tracer**: switch default span processor from `SimpleSpanProcessor` (sync export
per span) to `BatchSpanProcessor` (background queue + batch export). Reduces
overhead from 10x → ~7x baseline at 200 concurrent. Opt-in to sync export via
`Tracer(processor="simple")` for dev/test determinism.

**AuditLogger**: new `QueuedFileAuditStore` — non-blocking `append()` enqueues
event, background asyncio task batches + flushes every 100ms or 1000 events.
Trade-off: events may lose ~100ms on hard crash. For strict compliance audit,
use `backend="file"` (synchronous, durable per-event).

**Factory `audit=True`** now defaults to `backend="queued_file"` (non-blocking).
For per-event durability, instantiate `AuditLogger(config=AuditConfig(backend="file", ...))`
directly and inject via class-based agent.

**New API:**
- `Tracer(processor: Literal["batch", "simple"] = "batch")` — opt-in to sync mode
- `QueuedFileAuditStore(file_path, flush_interval_ms=100, max_batch_size=1000)`
- `QueuedFileAuditStore.shutdown()` — graceful drain remaining events
- `AuditConfig(backend="queued_file", file_path=...)` — factory-friendly config

**Tests:** +9 (5 queued audit + 4 batch tracer). Phase 8.8 perf comparison
re-verified shows tracer wall improved 40ms → 30.5ms.

**See:** `docs/architecture/phase-8.8-async-audit-report.md` for full analysis.

## [0.3.0a7] - 2026-05-21

### Verified — Phase 8.8: Async non-blocking audit on cross-cutting

Stress test (200 concurrent `Agent.run()`) confirms:
- **CostTracker** (in-memory) — ✅ non-blocking, ~0% overhead
- **RateLimiter** (anyio.sleep + in-memory) — ✅ non-blocking, ~0% overhead
- **Tracer** (default ConsoleExporter) — ⚠️ 10x wall overhead (still p99 0.38ms);
  switch to `BatchSpanProcessor` + OTLP for production
- **AuditLogger (File)** — ⚠️ 6x wall overhead (still p99 0.19ms); switch to
  `aiofiles` or background queue for 10k+ QPS

**Full report**: `docs/architecture/phase-8.8-async-audit-report.md`

**Test artifact**: `tests/perf/test_observability_concurrency.py` — re-run on
any cross-cutting code change to catch performance regression.

**No code changes shipped** — current behavior acceptable for typical load (< 1000
concurrent). Production fixes (`BatchSpanProcessor`, `QueuedFileAuditStore`)
documented for Phase 8.9+ when scale demands it.

## [0.3.0a6] - 2026-05-21

### Added — Phase 9.2: Extended hooks (4 events + parallel mode)

**4 new events:**
- `PRE_TOOL` / `POST_TOOL` — fire around each tool invocation. Use cases:
  PII scrub on args, approval gate before sensitive tools, metric per tool.
  `PreToolContext.replace(args=...)` lets handler mutate args before tool runs.
- `ON_BUDGET_EXCEEDED` — fires when `BudgetExceededError` raised by CostTracker.
- `ON_RATE_LIMITED` — fires when `RateLimitTimeout` raised by RateLimiter.

Specialized events fire BEFORE generic `ON_ERROR` (so user can both handle
specific case AND log all errors).

**Parallel fire mode:**
```python
registry.register(HookEvent.ON_COMPLETE, metric_emitter, mode="parallel")
```

Parallel handlers fire concurrently via `anyio.create_task_group()` after
sequential handlers complete. Exceptions in parallel handlers are **swallowed
and logged** (fire-and-forget semantic). Use for metrics, async logging, OTel
sinks where blocking the request path is unacceptable.

Sequential and parallel handlers can mix per event:
```python
registry.register(evt, seq_handler, mode="sequential")  # blocks, may mutate
registry.register(evt, par_handler, mode="parallel")    # fire-and-forget
```

**Factory integration:** `Agent(hooks={"pre_tool": [scrub]})` automatically
wraps each tool handler in registry to fire PRE_TOOL/POST_TOOL. Wrapping skipped
(zero overhead) when no tool hooks registered.

**Tests:** +10 unit (116 total Factory).

**See:** `docs/guides/hooks.md`, `docs/guides/quickstart.md` §1.6.

## [0.3.0a5] - 2026-05-21

### Added — Phase 9: Hook System (6 events MVP)

Dynamic lifecycle injection without subclassing. Pattern inspired by Claude Agent SDK.

```python
from ryuu import Agent
from ryuu.hooks import PreExecuteContext, PostExecuteContext, OnErrorContext

async def pii_scrub(ctx: PreExecuteContext) -> None:
    # Mutate task payload before execution
    ...

async def metric_emit(ctx: PostExecuteContext) -> None:
    prometheus.counter("agent_runs").inc()

agent = Agent(
    model="gpt-4o-mini",
    hooks={
        "pre_execute":  [pii_scrub],
        "post_execute": [metric_emit],
        "on_error":     [error_logger],
    },
)
```

**New module: `ryuu.hooks`**
- `HookEvent` enum: PRE_EXECUTE / POST_EXECUTE / PRE_LLM / POST_LLM / ON_ERROR / ON_COMPLETE
- Typed context dataclasses: `PreExecuteContext` / `PostExecuteContext` / `PreLLMContext` /
  `PostLLMContext` / `OnErrorContext` / `OnCompleteContext`
- `HookRegistry` — sequential fire (handlers run in registration order, may mutate ctx or raise)
- Sync + async handlers both supported

**Factory integration**: `Agent(hooks={"event_name": [callable]})` builds HookRegistry internally
and fires events at lifecycle points in `_FactoryLLMAgent._execute()`.

**Deferred to Phase 9.2:**
- pre_tool / post_tool / on_budget_exceeded / on_rate_limited events
- Parallel fire mode (fire-and-forget for metrics)
- Decorator / class-based registration styles

### Added — Phase 10.6: Token streaming + real failover dispatch

**Token-by-token streaming** when no tools present:
```python
async for ev in agent.stream("Explain quantum entanglement"):
    if ev.type == "token":
        print(ev.text, end="", flush=True)
    elif ev.type == "final":
        print()
```

Uses `provider.stream()` directly for per-chunk emission. ReAct streaming
(with tools) still uses semantic events (thought / tool_call / tool_result / final).

**Real failover dispatch**: when primary provider raises, automatically retry
with next provider in `model=[list]` fallback chain. All-fail → propagates last error.

```python
agent = Agent(model=["openai:gpt-4o", "anthropic:claude-sonnet-4"])
# Primary OpenAI down → automatic fallback to Anthropic
result = await agent.run("query")
```

**Tests:** +16 unit (16 hooks + 6 Phase 10.6 = 106 total Factory).

**See:** `docs/guides/quickstart.md` §1.6 (hooks), §1.7 (streaming).

## [0.3.0a4] - 2026-05-21

### Added — Phase 10.3: Tool Modes B + C + D

- **Mode B**: `tools=` accepts `ITool` instances (with state via constructor) in
  addition to callables. Heterogeneous list `tools=[callable, ITool, callable]` supported.
- **Mode C**: new `tool_registry=` kwarg — pass pre-built `ToolRegistry` directly
  (skips list introspection). Useful for DI + `allowed_domains` security.
- **Mode D**: when Mode 4 prompt + tool_registry/tools opted in, YAML tool schemas
  attached to matching handlers by name. Missing handler for YAML-defined tool → `ValueError`.

Validation: `tools=` + `tool_registry=` mutually exclusive.

### Added — Phase 10.4: Streaming + multi-provider fallback + budget_tokens

- **`Agent.stream(message_or_kwargs) -> AsyncIterator[StreamEvent]`** — yields events
  during execution: `thought` / `tool_call` / `tool_result` / `final` / `error`.
  Uses anyio memory stream to bridge ReActCallbacks → async iterator.
  Note: `token` event type defined but token-by-token streaming deferred to Phase 10.6.
- **`model: str | list[str]`** — accepts fallback chain. Primary is first, rest
  available as `_fallback_providers` (failover dispatch deferred to 10.6).
- **`budget_tokens: int | None`** — alt to `budget_usd` for token-count budgeting.

### Added — Phase 10.5: Multi-agent facades

5 pattern classes — `Chain`, `FanOut`, `Router`, `Orchestrator`, `Evaluator` —
all implement uniform `.run(input) -> output` for composability (nest freely).

```python
from ryuu import Agent, Chain, FanOut, Router, Orchestrator, Evaluator

# Chain — sequential pipeline (Agent OR callable transforms)
chain = Chain([extract_agent, str.upper, translate_agent])

# FanOut — 3 variants (data items / N agents / explicit pairs)
fan = FanOut(agent=worker, items=["g1", "g2"], template="Analyze {item}")
fan = FanOut(agents=[security_agent, perf_agent, style_agent])
fan = FanOut(pairs=[(a1, "task1"), (a2, "task2")])

# Router — analyzer dispatches
router = Router(routes={"a": ..., "_default": ...}, analyzer=lambda q: "a")

# Orchestrator — main plans + workers execute + aggregate
orch = Orchestrator(main=planner, workers=lambda i: Agent(...),
                    plan_items=lambda out: [...], aggregate=lambda outs: ...)

# Evaluator — generate → verify → refine
ev = Evaluator(generator=Agent(...), verifier=lambda o: (True, ""), max_refines=2)
```

Facades nest: `Chain([Router(...), FanOut(...), Evaluator(...)])` works because
each exposes `.run()`. Concurrent execution uses `anyio.create_task_group()`.

**Tests:** +37 unit (90 total: 35 Mode 1 + 8 Mode 2 + 4 Mode 3 + 6 Mode 4 +
9 Tools B/C/D + 12 Stream/Fallback/budget_tokens + 16 facades).

**See:** `docs/guides/quickstart.md` §1, §4, §5.16.

## [0.3.0a3] - 2026-05-21

### Added — Phase 10.2: Factory Mode 3 (file path) + Mode 4 (YAML reference)

**Mode 3 — file path** cho `system` và `user_template`:

```python
from pathlib import Path

agent = Agent(
    model="gpt-4o",
    system=Path("prompts/personas/analyst.md"),
    user_template=Path("prompts/templates/analyze.txt"),
)
```

File contents đọc tại `__post_init__` và lưu thành str. Missing file → `FileNotFoundError`.

**Mode 4 — YAML registry reference**:

```python
from pathlib import Path
from ryuu.prompts.registry import PromptRegistry

agent = Agent(
    model="gpt-4o",
    prompt="todo_app:v1:analyze",                          # "project:version:name"
    prompt_registry=PromptRegistry(prompts_root=Path("./prompts")),
)
# Hoặc bỏ prompt_registry → auto-detect ./prompts/
```

Load YAML config + extract system + user_template từ template name. Tools vẫn pass
qua Mode A (callable list) — Mode D (YAML tool integration) defer to Phase 10.3.

**New fields:**
- `system: str | Path | None` (expanded — Mode 3)
- `user_template: str | Path | None` (expanded — Mode 3)
- `prompt: str | None` (Mode 4 reference)
- `prompt_registry: PromptRegistry | None` (Mode 4 registry, default auto-detect)

**Validation Mode 4 mutual exclusion:**
- `prompt=` + `instructions/system/user_template/examples` → ValueError
- Format invalid (not "project:version:name") → ValueError
- Reference to non-existent prompt name → KeyError

**Tests:** +10 unit (53 total cho factory: 35 Mode 1 + 8 Mode 2 + 4 Mode 3 + 6 Mode 4).

**See:** `docs/guides/quickstart.md` §5.16.

## [0.3.0a2] - 2026-05-21

### Added — Phase 10.1: Factory Mode 2 (system + user_template + examples)

Mode 2 cho phép tách system prompt khỏi user prompt + inject few-shot examples,
phục vụ specialized domain reasoning (finance/medical) hoặc template-based input.

```python
from ryuu import Agent

agent = Agent(
    model="gpt-4o-mini",
    system="You are a translator. Output Vietnamese only.",
    user_template="Translate to VN: {text}",
    examples=[
        {"user": "Hello",  "assistant": "Xin chào"},
        {"user": "Thanks", "assistant": "Cảm ơn"},
    ],
)
result = await agent.run(text="Good morning")
```

**New fields trên `Agent`:**
- `system: str | None = None` — full system prompt (thay cho `instructions` shorthand)
- `user_template: str | None = None` — template với `{variables}`, fill qua `.run(**kwargs)`
- `examples: list[dict] | None = None` — few-shot list, mỗi item có keys `user`+`assistant`

**`.run()` behavior update:**
- `message` giờ là optional positional — nếu set `user_template`, không truyền message
- Kwargs tách thành 2 nhóm: reserved scope keys (`user_id`/`session_id`/`domain`/`correlation_id`)
  → ContextScope. Còn lại → template vars cho `user_template.format(**vars)`.

**Validation mới:**
- `instructions` + `system` cùng set → ValueError (mutual exclusion Mode 1/Mode 2)
- `examples` item thiếu `user` hoặc `assistant` key → ValueError
- `.run()` không có message AND không set `user_template` → ValueError

**Tests:** +8 unit tests (43 total cho factory).

**See:** `docs/guides/quickstart.md` §1.2.5, §5.16.

## [0.3.0a1] - 2026-05-21

### Added — Phase 10 MVP: Factory `Agent()`

Lean single-line agent creation for 90% chatbot + tool-calling use cases.
Class-based `BaseAgent` remains for advanced use cases — Factory does NOT replace it.

```python
from ryuu import Agent

def get_weather(city: str) -> dict:
    """Get current weather."""
    return {"city": city, "temp_c": 22}

agent = Agent(
    model="gpt-4o-mini",
    instructions="You are a helper",
    tools=[get_weather],
    budget_usd=1.0,
    audit=True,
    verbose=True,
)
result = await agent.run("Weather in Tokyo?", user_id="u-1")
```

**New public API:**
- `ryuu.Agent` — Factory dataclass with auto provider detect + tool schema introspection
- `Agent.run(message, **scope) -> AgentResult` — async dispatch with auto ContextScope

**Factory capabilities (MVP):**
- Mode 1 prompt: `instructions=str` shorthand for system prompt
- Mode A tools: inline callable list, schema auto-generated from docstring + type hints
- Provider auto-detect from model string (`gpt-`, `o1-`, `o3-`, `claude-` prefixes; explicit `openai:` / `anthropic:`)
- Per-call limits: `max_tokens`, `temperature`
- Per-run limit: `max_iterations` (ReAct loop cap)
- Per-session cap: `budget_usd` (raises `BudgetExceededError`)
- Cross-cutting toggles: `rate_limit_rps`, `audit`, `trace`, `verbose`
- Scope kwargs in `.run()`: `user_id`, `session_id`, `domain` → auto `ContextScope`

**Internal modules (private):**
- `ryuu._provider_detect` — model string → ILLMProvider
- `ryuu._tool_introspect` — callable → OpenAI function-calling schema
- `ryuu.factory._FactoryLLMAgent` — concrete LLMAgent subclass wrapped by Factory

**Tests:** 35 unit + 2 integration (skipped without `OPENAI_API_KEY`).

**Examples:** `examples/factory_quickstart/{chatbot,tool_calling,production}.py`

**Deferred to Phase 10.x:**
- Prompt Modes 2-4 (separate system/user, file path, YAML registry reference)
- `hooks=` param (after Phase 9 Hook System)
- `.stream()` AsyncIterator
- Multi-provider fallback chain
- `tool_registry=` direct pass

**See:** `docs/guides/quickstart.md` §1, `tasks/plan-phase10-factory.md`.

## [0.2.0a1] - UNRELEASED

### BREAKING CHANGES — Phase 8.1 (Workflow as independent library)

`ryuu-workflow` is now a **standalone PyPI package** with its own namespace `ryuu_workflow`.
The following imports no longer work after this release:

```python
# REMOVED — migrate to ryuu_workflow.*
from ryuu.workflow.engine import WorkflowEngine
from ryuu.observability.errors import RetryableError, DegradedError, FatalError
from ryuu.runtime.context import ExecutionContext, ContextScope
from ryuu import WorkflowEngine  # top-level re-export removed
```

See `packages/MIGRATION.md` for the full sed migration map.

### Migration

```bash
pip install ryuu-workflow   # standalone (anyio only)
pip install ryuu            # full AI framework (auto-pulls ryuu-workflow)
```

### Added

- `packages/ryuu-workflow/` — standalone wheel, `anyio` as only dep
- `packages/MIGRATION.md` — mechanical sed migration map
- `scripts/install-dev.sh` — editable install for both packages in dev

### Removed

- `ryuu/workflow/` — moved to `ryuu_workflow`

---

### Phase 8.3 — `ryuu-providers` standalone LLM provider package

#### Added

- `packages/ryuu-providers/` — new standalone wheel; deps: `ryuu-core`, `pyyaml`; optional: `openai`, `anthropic`
  - `ryuu_providers.llm` — `ILLMProvider` Protocol, `CompletionRequest`, `Response`, `Message`, `TokenUsage`, `Embedding`
  - `ryuu_providers.circuit_breaker` — `CircuitBreaker`, `CircuitState`
  - `ryuu_providers.fallback` — `ProviderFallbackChain`
  - `ryuu_providers.router` — `ModelRouter`
  - `ryuu_providers.adapters.openai` — `OpenAIProvider`
  - `ryuu_providers.adapters.anthropic` — `AnthropicProvider`
  - `ryuu_providers._pricing` — `calculate_usd`, `reload_pricing`, `PRICING`, `CONTEXT_WINDOW`
- `scripts/test-providers-isolation.sh` — proves `import ryuu` fails in fresh venv with only `ryuu-providers`
- `providers-isolation` CI job — runs on every PR

#### Changed

- `ryuu/providers/*.py` — replaced with backward-compat shims (re-export from `ryuu_providers`)
- `ryuu/observability/_pricing.py` — replaced with smart shim using `__getattr__` for live state forwarding
- Root `pyproject.toml` — added `ryuu-providers>=0.2.0a1` dep; removed direct `pyyaml` dep (now transitive via ryuu-providers)
- `packages/MIGRATION.md` — Phase 8.3 section added

---

### Phase 8.9 — `ryuu-guardrail` + `ryuu-eval` new packages

#### Added — `ryuu-guardrail`

- `packages/ryuu-guardrail/` — new standalone wheel; deps: `ryuu-core`
  - `ryuu_guardrail.protocol` — `GuardrailAction`, `GuardrailResult`, `IGuardrail`, `GuardrailBlockedError`
  - `ryuu_guardrail.passthrough` — `PassthroughGuardrail` (NullObject, zero overhead)
  - `ryuu_guardrail.filters.pii` — `PIIFilter` (regex: email/phone/SSN/CC → REDACT)
  - `ryuu_guardrail.filters.topic` — `TopicBlocker` (config deny list → BLOCK)
  - `ryuu_guardrail.filters.injection` — `PromptInjectionDetector` (jailbreak patterns → BLOCK)
  - `ryuu_guardrail.pipeline` — `GuardrailPipeline`, `TrustLevel` (LOW/MEDIUM/HIGH factory)
- `scripts/test-guardrail-isolation.sh` — isolation test
- `guardrail-isolation` CI job

#### Added — `ryuu-eval`

- `packages/ryuu-eval/` — new standalone wheel (dev dependency); deps: `ryuu-core`, `ryuu-providers`
  - `ryuu_eval.models` — `EvalCase`, `ScoreResult`, `CaseResult`, `SuiteResult`
  - `ryuu_eval.protocols` — `EvalTarget`, `Scorer` Protocols
  - `ryuu_eval.scorers` — `ExactMatch`, `Constraint`, `Threshold`, `Composite`, `LLMJudge`
  - `ryuu_eval.fixture_loader` — `FixtureLoader` (JSON fixture loading)
  - `ryuu_eval.runner` — `EvalRunner` (budget-aware async orchestration)
  - `ryuu_eval.renderers.terminal` — `TerminalRenderer`
  - `ryuu_eval.renderers.github_actions` — `GitHubActionsRenderer`
  - `ryuu_eval.renderers.api` — `ApiRenderer`
- `scripts/test-eval-isolation.sh` — isolation test
- `eval-isolation` CI job

#### CI gate (Phase 8.9 complete)
- `pytest`: **776 passed, 1 skipped** (18 guardrail + 16 eval new tests)
- Both isolation jobs: PASSED

---

### Phase 8.8 — `ryuu-knowledge-*` standalone knowledge packages

#### Added

- `packages/ryuu-knowledge-base/` — zero-dep protocol package
  - `ryuu_knowledge_base.backbone` — `BackboneType`, `QueryResult`, `AssembledContext`, `IKnowledgeBackbone`
  - `ryuu_knowledge_base.context_assembler` — `ContextAssembler`
- `packages/ryuu-knowledge-memory/` — memory backbone; deps: `ryuu-knowledge-base`
  - `ryuu_knowledge_memory.store` — `MemoryLayer`, `MemoryEntry`, `IMemoryStore`
  - `ryuu_knowledge_memory.working` — `WorkingMemoryStore` (bounded FIFO)
  - `ryuu_knowledge_memory.episodic` — `EpisodicMemoryStore` (keyword-search)
  - `ryuu_knowledge_memory.backbone` — `MemoryBackbone`
- `packages/ryuu-knowledge-graph/` — graph backbone; deps: `ryuu-knowledge-base`
  - `ryuu_knowledge_graph.store` — `Node`, `Edge`, `IGraphStore`
  - `ryuu_knowledge_graph.in_memory` — `InMemoryGraphStore` (BFS neighbors, substring search)
  - `ryuu_knowledge_graph.backbone` — `GraphBackbone`
- `packages/ryuu-knowledge/` — hybrid orchestrator; deps: `ryuu-knowledge-base` + memory + graph
  - `ryuu_knowledge.hybrid` — `HybridBackbone` (60/40 budget split)
- `scripts/test-knowledge-isolation.sh` — proves `import ryuu` fails in fresh venv with only knowledge packages
- `knowledge-isolation` CI job — runs on every PR

#### Changed

- `ryuu/knowledge/backbone.py`, `context_assembler.py`, `hybrid.py` — replaced with backward-compat shims
- `ryuu/knowledge/memory/*.py` — replaced with backward-compat shims
- `ryuu/knowledge/graph/*.py` — replaced with backward-compat shims
- Root `pyproject.toml` — added `ryuu-knowledge-{base,memory,graph}>=0.2.0a1` + `ryuu-knowledge>=0.2.0a1` deps
- `packages/MIGRATION.md` — Phase 8.8 section added

#### CI gate (Phase 8.8 complete)
- `pytest`: **742 passed, 1 skipped** (18 new knowledge_pkg tests)
- `knowledge-isolation` job: PASSED

---

### Phase 8.7 — `ryuu-runtime` standalone runtime package

#### Added

- `packages/ryuu-runtime/` — new standalone wheel; deps: `ryuu-core`, `ryuu-providers`, `ryuu-cognitive`, `ryuu-execution`
  - `ryuu_runtime.analyzer` — `IIntentAnalyzer` Protocol
  - `ryuu_runtime.llm_analyzer` — `LLMIntentAnalyzer`, `INTENT_SYSTEM_PROMPT`
  - `ryuu_runtime.selector` — `StrategySelector`
  - `ryuu_runtime.request_handler` — `RequestHandler`
- `scripts/test-runtime-isolation.sh` — proves `import ryuu` fails in fresh venv with only `ryuu-runtime`
- `runtime-isolation` CI job — runs on every PR

#### Changed

- `ryuu/intent/analyzer.py`, `llm_analyzer.py`, `selector.py` — replaced with backward-compat shims
- `ryuu/runtime/request_handler.py` — replaced with backward-compat shim
- Root `pyproject.toml` — added `ryuu-runtime>=0.2.0a1` dep
- `packages/MIGRATION.md` — Phase 8.7 section added

#### CI gate (Phase 8.7 complete)
- `pytest`: **702 passed, 1 skipped** (11 new runtime_pkg tests)
- `runtime-isolation` job: PASSED

---

### Phase 8.6 — `ryuu-execution` standalone execution package

#### Added

- `packages/ryuu-execution/` — new standalone wheel; deps: `ryuu-core`, `ryuu-providers`, `anyio`
  - `ryuu_execution.agent` — `BaseAgent` (template method, cross-cutting), re-exports `Task`, `AgentResult`
  - `ryuu_execution.llm_agent` — `LLMAgent`, `ReActCallbacks`, `SilentCallbacks`, `PrintCallbacks`, `BudgetSummary`, `ModelPolicy`
  - `ryuu_execution.pool` — `AgentPool` (round-robin/random routing, fan_out with fail_fast/collect modes)
  - `ryuu_execution.tool_registry` — `ITool`, `ToolRegistry` (domain allowlist, callable wrapper)
  - `ryuu_execution.sandbox` — `SandboxResult`, `ISandbox`, `SubprocessSandbox`, `SandboxManager`
- `scripts/test-execution-isolation.sh` — proves `import ryuu` fails in fresh venv with only `ryuu-execution`
- `execution-isolation` CI job — runs on every PR

#### Changed

- `ryuu/execution/*.py` — replaced with backward-compat shims (re-export from `ryuu_execution`)
- Root `pyproject.toml` — added `ryuu-execution>=0.2.0a1` dep
- `packages/MIGRATION.md` — Phase 8.6 section added

#### CI gate (Phase 8.6 complete)
- `pytest`: **691 passed, 1 skipped** (10 new execution_pkg tests)
- `execution-isolation` job: PASSED

---

### Phase 8.5 — `ryuu-cognitive` standalone cognitive package

#### Added

- `packages/ryuu-cognitive/` — new standalone wheel; deps: `ryuu-core`, `ryuu-providers`
  - `ryuu_cognitive.verifier` — `VerificationResult`, `IVerifier`
  - `ryuu_cognitive.strategy` — `IAgentPool`, `ICognitiveStrategy`
  - `ryuu_cognitive.strategies` — `DirectStrategy`, `ReActStrategy`, `EvaluatorOptimizerStrategy`, `ParallelFanoutStrategy`, `ISubtaskBuilder`, `EntitySubtaskBuilder`
  - `ryuu_cognitive.verifiers` — `GroundTruthVerifier`, `SchemaVerifier`, `LLMJudgeVerifier`, `VerifierPipeline`, `PipelineMode`
- `scripts/test-cognitive-isolation.sh` — proves `import ryuu` fails in fresh venv with only `ryuu-cognitive`
- `cognitive-isolation` CI job — runs on every PR

#### Changed

- `ryuu/cognitive/verifier.py`, `strategy.py`, `strategies/*.py`, `verifiers/*.py` — replaced with backward-compat shims
- Root `pyproject.toml` — added `ryuu-cognitive>=0.2.0a1` dep
- `packages/MIGRATION.md` — Phase 8.5 section added

#### CI gate (Phase 8.5 complete)
- `pytest`: **681 passed, 1 skipped** (14 new cognitive_pkg tests)
- `cognitive-isolation` job: PASSED

---

### Phase 8.4 — `ryuu-observability` standalone observability package

#### Added

- `packages/ryuu-observability/` — new standalone wheel; deps: `ryuu-core`, `anyio`, `opentelemetry-api`, `opentelemetry-sdk`
  - `ryuu_observability.cost` — `CostPolicy`, `UsageSnapshot`, `ICostStore`, `InMemoryCostStore`, `CostTracker`
  - `ryuu_observability.audit` — `AuditEvent`, `AuditConfig`, `IAuditStore`, `ConsoleAuditStore`, `FileAuditStore`, `AuditLogger`, `verify_chain`, `_GENESIS_HASH`
  - `ryuu_observability.tracer` — `Tracer`, `setup_tracing`, `get_current_correlation_id`
  - `ryuu_observability.rate_limit` — `RatePolicy`, `IRateStore`, `InMemoryRateStore`, `RateLimiter`
- `scripts/test-observability-isolation.sh` — proves `import ryuu` fails in fresh venv with only `ryuu-observability`
- `observability-isolation` CI job — runs on every PR

#### Changed

- `ryuu/observability/cost.py`, `audit.py`, `tracer.py`, `rate_limit.py` — replaced with backward-compat shims (re-export from `ryuu_observability`)
- Root `pyproject.toml` — added `ryuu-observability>=0.2.0a1` dep; removed direct `opentelemetry-api`/`opentelemetry-sdk` (now transitive)
- `packages/MIGRATION.md` — Phase 8.4 section added

#### CI gate (Phase 8.4 complete)
- `pytest`: **667 passed, 1 skipped** (12 new observability_pkg tests)
- `observability-isolation` job: PASSED

---

### Phase 8.2 — `ryuu-core` zero-dependency foundation package

#### Added

- `packages/ryuu-core/` — new standalone wheel with **zero runtime deps** (stdlib only)
  - `ryuu_core.errors` — all framework error types and retry utilities
  - `ryuu_core.context` — `ContextScope`, `ExecutionContext` frozen dataclasses
  - `ryuu_core.models` — `Cost`, `Task`, `AgentResult`, intent/cognitive model types
  - `ryuu_core.protocols` — `ICostTracker`, `ITracer`, `IAuditLogger`, `IRateLimiter`
  - `ryuu_core.nulls` — `NullCostTracker`, `NullTracer`, `NullAuditLogger`, `NullRateLimiter`
- `scripts/test-core-isolation.sh` — fresh-venv proof of zero-dep isolation
- CI job `core-isolation` — runs on every PR

#### Changed

- `ryuu_workflow.errors` and `ryuu_workflow.context` are now thin re-exports from `ryuu_core`
- `ryuu.intent.models` is now a thin re-export from `ryuu_core.models`
- `ryuu.execution.agent` — `Task` and `AgentResult` re-exported from `ryuu_core.models`
- `BaseAgent` observability deps (`cost_tracker`, `tracer`, `audit_logger`, `rate_limiter`) now default to NullObjects — construction with only `agent_id` is supported
- Root `pyproject.toml` adds `ryuu-core>=0.2.0a1` as a runtime dependency

#### Migration

No callsite changes required. All prior import paths continue to work via re-exports.
New code should import directly from `ryuu_core.*`.
- `ryuu/observability/errors.py` — moved to `ryuu_workflow.errors`
- `ryuu/runtime/context.py` — moved to `ryuu_workflow.context`
- Top-level re-exports of workflow symbols from `ryuu/__init__.py`

## [0.1.0b7] - 2026-05-08

### Added (Phase 7 — Workflow Engine + State Machine + Checkpoint)

- `ryuu/workflow/` module: `ICheckpointStore`, `Checkpoint`, `InMemoryCheckpointStore`, `FileCheckpointStore`
- `IState` Protocol + `StateTransition` + `Workflow` dataclass + `StateMachine`
- `IWorkflowEngine` Protocol + `WorkflowEngine` with `run()` + `resume()` (SIGKILL-safe recovery)
- Tiered error handling in engine: RetryableError (exponential backoff retry), DegradedError (log + fail gracefully), FatalError (immediate stop) — engine always returns `WorkflowResult`, never raises
- `FileCheckpointStore`: atomic JSON writes via tmpfile → `os.replace`; raises `FatalError` on non-serializable output
- `FakeCheckpointStore` + `FakeWorkflowEngine` in `ryuu/_testing/fakes.py` for product-side tests
- Parametric contract tests for `ICheckpointStore` impls (InMemory + File) + `IWorkflowEngine`
- Integration smoke: full PARSE → ENRICH → DERIVE pipeline + SIGKILL crash simulation via `FileCheckpointStore`
- Public API exports from `ryuu`: `WorkflowEngine`, `Workflow`, `IState`, `ICheckpointStore`, `FileCheckpointStore`, `InMemoryCheckpointStore`, `WorkflowResult`, `WorkflowStatus`, `StateTransition`, `StateMachine`, `Checkpoint`

### Changed

- `ryuu.__version__` bumped `0.1.0b6` → `0.1.0b7`

## [0.1.0b6] - 2026-05-08

### Added (Phase 6 — Multi-Agent Orchestration)
- `ryuu/execution/pool.py` — `AgentPool`: concrete `IAgentPool` with:
  - `register(agent, tags)` + `agents_with_tag(tag)` + `agent_ids()`
  - `dispatch(task, context, strategy)` — round_robin (default) or random routing; no "first registered" silent bug
  - `dispatch_to(agent_id, task, context)` — explicit routing by id
  - `fan_out(tasks, context, tag_filter, on_error)` — parallel dispatch via `anyio.create_task_group()`; bounded by `Semaphore(max_concurrency)`; index-stable results
  - `on_error="fail_fast"` (default): 1 failure raises `ExceptionGroup` / `on_error="collect"`: partial results collected as `AgentResult(success=False)`
- `ryuu/cognitive/strategies/parallel.py` — `ParallelFanoutStrategy` (ICognitiveStrategy #4):
  - `ISubtaskBuilder` Protocol + `EntitySubtaskBuilder` default (1 task per entity)
  - Decomposes HIGH-complexity intent → N subtasks → `fan_out(on_error="collect")` → aggregate → verify
  - Custom builder injectable via constructor
- `ryuu/intent/models.py` — `PARALLEL_FANOUT` strategy id constant
- `ryuu/cognitive/strategies/__init__.py` — now exports all 4 strategies + ISubtaskBuilder

### Changed
- `examples/code_analysis/agents.py` — `CodebaseAnalysisOrchestrator` replaced `asyncio.gather` + manual semaphore with `AgentPool.fan_out(on_error="collect")`; removed `import asyncio`
- `ryuu/_testing/fakes.py` — `FakeAgentPool` gains `fan_out(tasks, context, on_error)` method
- `ryuu/execution/__init__.py` — exports `AgentPool`
- `ryuu/cognitive/strategies/__init__.py` — exports `ParallelFanoutStrategy`, `ISubtaskBuilder`, `EntitySubtaskBuilder`

### Design decisions
- `dispatch()` uses round_robin instead of "first registered" — predictable under load (expert review Fix #7)
- `fan_out` has explicit `on_error` semantics — no implicit cancel-all surprise (expert review Fix #6)
- `OrchestratorAgent` deferred — duplicate with `ParallelFanoutStrategy`; no concrete framework use case yet (expert review Fix #5)
- `asyncio.gather` eliminated from `ryuu/` and `examples/` — spec §5 compliance

### CI gate
- `ruff check ryuu/ tests/ examples/`: 0 violations (new files)
- `mypy ryuu/ examples/`: 0 errors
- `pytest`: 487 passed, 1 skipped; coverage 87.77% ≥ 88% threshold
- `grep -r "asyncio.gather" ryuu/ examples/code_analysis/`: no results

## [0.1.0b5+examples] - 2026-05-07

### Added (Example Apps — PromptRegistry + OpenAI refactor)
- `ryuu/prompts/` package: `PromptRegistry` + `PromptConfig` + `ToolDefinition` + `_SafeFormatter`
  - Loads versioned YAML → `PromptConfig`; renders `CompletionRequest` with variable substitution
  - `_SafeFormatter` leaves unknown `{placeholders}` intact instead of raising `KeyError`
- `prompts/todo_app/v1.yaml` — 3 prompt templates + 3 tool schemas; model: `gpt-4o-mini`
- `prompts/code_analysis/v1.yaml` — 2 prompt templates + 3 tool schemas; model: `gpt-4o-mini`
- `ryuu/providers/adapters/openai.py` — `Response.metadata["tool_calls"]` now populated from OpenAI tool call responses
- `examples/todo_app/` — `TodoAnalysisAgent` + `build_todo_registry` + YAML prompts + `_tool_loop()` + OpenAI/Fake fallback
- `examples/code_analysis/` — `ClassAnalysisAgent` (per-class parallel) + `CodebaseAnalysisOrchestrator` + YAML prompts + `ToolRegistry` + `GraphBackbone`

### Architecture patterns demonstrated
- Schema-handler separation: YAML defines what LLM sees; Python handler executes it
- `build_provider()`: `OpenAIProvider` if `OPENAI_API_KEY` set, else `FakeLLMProvider` (demo mode)
- `_tool_loop()`: standard OpenAI function-calling loop (LLM → tool_calls → execute → LLM)
- `AgentFactory`: shares one `OpenAIProvider` across 78 parallel `ClassAnalysisAgent` instances in code_analysis

### CI gate
- `ruff check ryuu/ examples/`: 0 violations (70 files)
- `mypy ryuu/ examples/ --ignore-missing-imports`: 0 errors (70 files)
- `pytest`: 383 passed, 1 skipped

## [0.1.0b5] - 2026-05-07

### Added
- Phase 5 Integration Guide + Cookbook (replaces `examples/` apps per team decision)
- `docs/guides/getting-started.md` — install → first agent in < 5 min; covers `FakeLLMProvider`, `OpenAIProvider`, `AnthropicProvider`, `ModelRouter`
- `docs/guides/migration.md` — strangler pattern, shadow mode, canary release, rollback < 5 min
- `docs/cookbook/01-todo-app.md` — `MemoryBackbone` + `DirectStrategy` full wiring
- `docs/cookbook/02-flashcard-system.md` — `EpisodicMemoryStore` + SM-2 spaced repetition pattern
- `docs/cookbook/03-coding-practice.md` — `SandboxManager` + security considerations
- `docs/cookbook/04-stock-trading.md` — `AuditLogger` + `VerifierPipeline` + trust=HIGH patterns
- `tests/docs/test_doc_snippets.py` — validates all Python code blocks in docs compile + import paths exist

### CI gate (Phase 5 complete)
- `ruff check`: 0 violations
- `mypy ryuu/`: 0 errors (55 source files)
- `pytest --cov=ryuu`: 383 passed, 1 skipped, coverage **91.48%** (gate: 85%)

## [0.1.0b4] - 2026-05-07

### Added
- Phase 4 Provider Router + Circuit Breaker
- `CircuitBreaker` — CLOSED/OPEN/HALF_OPEN state machine; thread-safe; configurable `failure_threshold` + `recovery_timeout`
- `ModelRouter` — routes `CompletionRequest` by model tier (CHEAP/STANDARD/POWERFUL) via `_model_to_tier()`; per-provider `CircuitBreaker`; fallback provider on open circuit; fully implements `ILLMProvider`
- `ProviderFallbackChain` — tries providers in order; skips on `RetryableError`/`DegradedError`; raises `DegradedError("All providers failed")` when exhausted; fully implements `ILLMProvider`
- Contract tests: `ModelRouter` + `ProviderFallbackChain` satisfy `ILLMProvider` contract (`test_provider_contract.py`)
- Integration smoke: circuit trip + recovery + tier routing end-to-end (`test_phase4_smoke.py`)

### CI gate (Phase 4 complete)
- `ruff check`: 0 violations
- `mypy ryuu/`: 0 errors (55 source files)
- `pytest --cov=ryuu`: 363 passed, 1 skipped, coverage **91.48%** (gate: 85%)

## [0.1.0b3] - 2026-05-07

### Added
- Phase 3 Knowledge Backbone: `IKnowledgeBackbone` Protocol + `BackboneType`, `QueryResult`, `AssembledContext` models
- `IMemoryStore` Protocol + `MemoryLayer` enum + `MemoryEntry` dataclass
- `WorkingMemoryStore` — bounded FIFO deque per scope
- `EpisodicMemoryStore` — time-ordered, keyword-overlap scoring
- `MemoryBackbone` — wires working + episodic layers; assembles with token budget
- `IGraphStore` Protocol + `Node`, `Edge` models
- `InMemoryGraphStore` — dict + adjacency-list, BFS neighbor expansion, substring text search
- `GraphBackbone` — observation nodes, graph-based retrieval + context assembly
- `HybridBackbone` — 60/40 budget split across GraphBackbone + MemoryBackbone
- `ContextAssembler` — thin delegation facade over any `IKnowledgeBackbone`
- `FakeKnowledgeBackbone` upgraded to fully implement `IKnowledgeBackbone` Protocol (async, str observations)
- Contract tests for all 4 backbone impls (`test_backbone_contract.py`)
- Integration smoke: `ContextAssembler` + `EvaluatorOptimizerStrategy` end-to-end (`test_phase3_smoke.py`)

### CI gate (Phase 3 complete)
- `ruff check`: 0 violations
- `mypy ryuu/`: 0 errors (52 source files)
- `pytest --cov=ryuu`: 322 passed, 1 skipped, coverage **91.90%** (gate: 85%)

## [0.1.0b2] - 2026-05-07

### Added
- Phase 2 Verifier first-class: `IVerifier` + `VerificationResult` relocated to `ryuu/cognitive/verifier.py`
- `SchemaVerifier` — validates JSON keys or raw substrings in output
- `LLMJudgeVerifier` — uses LLM to score output quality (SCORE/VERDICT/REASON format), configurable threshold
- `GroundTruthVerifier` — exact, substring, and Jaccard word-overlap comparison against a reference
- `VerifierPipeline` — runs multiple verifiers with `ALL_PASS`, `ANY_PASS`, or `THRESHOLD` aggregation modes
- `FakeVerifier` updated: `feedback` param, import moved to `ryuu.cognitive.verifier`
- Contract tests for all 4 verifiers (`test_verifier_contract.py`)
- Integration smoke: `EvaluatorOptimizerStrategy` + `VerifierPipeline` end-to-end (`test_phase2_smoke.py`)

### CI gate (Phase 2 complete)
- `ruff check`: 0 violations
- `mypy ryuu/`: 0 errors (39 source files)
- `pytest --cov=ryuu`: 245 passed, 1 skipped, coverage **90.21%** (gate: 85%)

## [0.1.0b1] - 2026-05-07

### Added
- Phase 1 Intent tier: `StructuredIntent`, `ComplexityLevel`, `ModelTier`, `StrategyId` constants
- `IIntentAnalyzer` Protocol + `LLMIntentAnalyzer` (LLM-backed, JSON-structured output with fallback)
- `StrategySelector` — ordered strategy list, first-match routing
- `ICognitiveStrategy` Protocol + `IAgentPool` + `IVerifier` stub (`VerificationResult`)
- `DirectStrategy` — single-pass dispatch (catch-all, complexity-independent)
- `ReActStrategy` — think→act→observe loop with DONE signal, configurable `max_steps`
- `EvaluatorOptimizerStrategy` — generate→verify→refine loop, configurable `max_rounds`
- Test utilities: `FakeIntentAnalyzer`, `FakeAgentPool`, `FakeVerifier`
- Contract tests for all strategies (`test_strategy_contract.py`) and analyzers (`test_intent_analyzer_contract.py`)

### CI gate (Phase 1 complete)
- `ruff check`: 0 violations
- `mypy ryuu/`: 0 errors (33 source files)
- `pytest --cov=ryuu`: 192 passed, 1 skipped, coverage **88.77%** (gate: 85%)

## [0.1.0a1] - 2026-05-07

### Added
- Phase 0 Foundation: `BaseAgent` template method with cross-cutting (cost/trace/audit/rate-limit)
- Tiered error model: `RetryableError`, `DegradedError`, `FatalError` with exponential backoff retry policy
- `CostTracker` with per-scope budget enforcement and `CostPolicy` (per-user/day, per-domain/month, global/hour)
- `Tracer` via OpenTelemetry with correlation-ID propagation via `contextvars`
- `AuditLogger` with sha256 hash-chain JSONL backend (append-only, tamper-detectable)
- `RateLimiter` token-bucket per scope, async-safe via anyio
- `ILLMProvider` Protocol + `OpenAIProvider` and `AnthropicProvider` adapters
- `SandboxManager` v0.1 subprocess-based with platform-aware resource limits
- `ryuu._testing` public test utilities (`FakeLLMProvider`, `FakeKnowledgeBackbone`, pytest fixtures)

### CI gate (Phase 0 complete)
- `ruff check`: 0 violations
- `mypy ryuu/`: 0 errors (22 source files)
- `pytest --cov=ryuu`: 114 passed, 1 skipped, coverage **87.18%** (gate: 85%)
