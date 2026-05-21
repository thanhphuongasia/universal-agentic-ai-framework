# Changelog

All notable changes to RYUU follow [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
