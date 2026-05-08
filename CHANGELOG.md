# Changelog

All notable changes to UAAF follow [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0b7] - 2026-05-08

### Added (Phase 7 — Workflow Engine + State Machine + Checkpoint)

- `uaaf/workflow/` module: `ICheckpointStore`, `Checkpoint`, `InMemoryCheckpointStore`, `FileCheckpointStore`
- `IState` Protocol + `StateTransition` + `Workflow` dataclass + `StateMachine`
- `IWorkflowEngine` Protocol + `WorkflowEngine` with `run()` + `resume()` (SIGKILL-safe recovery)
- Tiered error handling in engine: RetryableError (exponential backoff retry), DegradedError (log + fail gracefully), FatalError (immediate stop) — engine always returns `WorkflowResult`, never raises
- `FileCheckpointStore`: atomic JSON writes via tmpfile → `os.replace`; raises `FatalError` on non-serializable output
- `FakeCheckpointStore` + `FakeWorkflowEngine` in `uaaf/_testing/fakes.py` for product-side tests
- Parametric contract tests for `ICheckpointStore` impls (InMemory + File) + `IWorkflowEngine`
- Integration smoke: full PARSE → ENRICH → DERIVE pipeline + SIGKILL crash simulation via `FileCheckpointStore`
- Public API exports from `uaaf`: `WorkflowEngine`, `Workflow`, `IState`, `ICheckpointStore`, `FileCheckpointStore`, `InMemoryCheckpointStore`, `WorkflowResult`, `WorkflowStatus`, `StateTransition`, `StateMachine`, `Checkpoint`

### Changed

- `uaaf.__version__` bumped `0.1.0b6` → `0.1.0b7`

## [0.1.0b6] - 2026-05-08

### Added (Phase 6 — Multi-Agent Orchestration)
- `uaaf/execution/pool.py` — `AgentPool`: concrete `IAgentPool` with:
  - `register(agent, tags)` + `agents_with_tag(tag)` + `agent_ids()`
  - `dispatch(task, context, strategy)` — round_robin (default) or random routing; no "first registered" silent bug
  - `dispatch_to(agent_id, task, context)` — explicit routing by id
  - `fan_out(tasks, context, tag_filter, on_error)` — parallel dispatch via `anyio.create_task_group()`; bounded by `Semaphore(max_concurrency)`; index-stable results
  - `on_error="fail_fast"` (default): 1 failure raises `ExceptionGroup` / `on_error="collect"`: partial results collected as `AgentResult(success=False)`
- `uaaf/cognitive/strategies/parallel.py` — `ParallelFanoutStrategy` (ICognitiveStrategy #4):
  - `ISubtaskBuilder` Protocol + `EntitySubtaskBuilder` default (1 task per entity)
  - Decomposes HIGH-complexity intent → N subtasks → `fan_out(on_error="collect")` → aggregate → verify
  - Custom builder injectable via constructor
- `uaaf/intent/models.py` — `PARALLEL_FANOUT` strategy id constant
- `uaaf/cognitive/strategies/__init__.py` — now exports all 4 strategies + ISubtaskBuilder

### Changed
- `examples/code_analysis/agents.py` — `CodebaseAnalysisOrchestrator` replaced `asyncio.gather` + manual semaphore with `AgentPool.fan_out(on_error="collect")`; removed `import asyncio`
- `uaaf/_testing/fakes.py` — `FakeAgentPool` gains `fan_out(tasks, context, on_error)` method
- `uaaf/execution/__init__.py` — exports `AgentPool`
- `uaaf/cognitive/strategies/__init__.py` — exports `ParallelFanoutStrategy`, `ISubtaskBuilder`, `EntitySubtaskBuilder`

### Design decisions
- `dispatch()` uses round_robin instead of "first registered" — predictable under load (expert review Fix #7)
- `fan_out` has explicit `on_error` semantics — no implicit cancel-all surprise (expert review Fix #6)
- `OrchestratorAgent` deferred — duplicate with `ParallelFanoutStrategy`; no concrete framework use case yet (expert review Fix #5)
- `asyncio.gather` eliminated from `uaaf/` and `examples/` — spec §5 compliance

### CI gate
- `ruff check uaaf/ tests/ examples/`: 0 violations (new files)
- `mypy uaaf/ examples/`: 0 errors
- `pytest`: 487 passed, 1 skipped; coverage 87.77% ≥ 88% threshold
- `grep -r "asyncio.gather" uaaf/ examples/code_analysis/`: no results

## [0.1.0b5+examples] - 2026-05-07

### Added (Example Apps — PromptRegistry + OpenAI refactor)
- `uaaf/prompts/` package: `PromptRegistry` + `PromptConfig` + `ToolDefinition` + `_SafeFormatter`
  - Loads versioned YAML → `PromptConfig`; renders `CompletionRequest` with variable substitution
  - `_SafeFormatter` leaves unknown `{placeholders}` intact instead of raising `KeyError`
- `prompts/todo_app/v1.yaml` — 3 prompt templates + 3 tool schemas; model: `gpt-4o-mini`
- `prompts/code_analysis/v1.yaml` — 2 prompt templates + 3 tool schemas; model: `gpt-4o-mini`
- `uaaf/providers/adapters/openai.py` — `Response.metadata["tool_calls"]` now populated from OpenAI tool call responses
- `examples/todo_app/` — `TodoAnalysisAgent` + `build_todo_registry` + YAML prompts + `_tool_loop()` + OpenAI/Fake fallback
- `examples/code_analysis/` — `ClassAnalysisAgent` (per-class parallel) + `CodebaseAnalysisOrchestrator` + YAML prompts + `ToolRegistry` + `GraphBackbone`

### Architecture patterns demonstrated
- Schema-handler separation: YAML defines what LLM sees; Python handler executes it
- `build_provider()`: `OpenAIProvider` if `OPENAI_API_KEY` set, else `FakeLLMProvider` (demo mode)
- `_tool_loop()`: standard OpenAI function-calling loop (LLM → tool_calls → execute → LLM)
- `AgentFactory`: shares one `OpenAIProvider` across 78 parallel `ClassAnalysisAgent` instances in code_analysis

### CI gate
- `ruff check uaaf/ examples/`: 0 violations (70 files)
- `mypy uaaf/ examples/ --ignore-missing-imports`: 0 errors (70 files)
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
- `mypy uaaf/`: 0 errors (55 source files)
- `pytest --cov=uaaf`: 383 passed, 1 skipped, coverage **91.48%** (gate: 85%)

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
- `mypy uaaf/`: 0 errors (55 source files)
- `pytest --cov=uaaf`: 363 passed, 1 skipped, coverage **91.48%** (gate: 85%)

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
- `mypy uaaf/`: 0 errors (52 source files)
- `pytest --cov=uaaf`: 322 passed, 1 skipped, coverage **91.90%** (gate: 85%)

## [0.1.0b2] - 2026-05-07

### Added
- Phase 2 Verifier first-class: `IVerifier` + `VerificationResult` relocated to `uaaf/cognitive/verifier.py`
- `SchemaVerifier` — validates JSON keys or raw substrings in output
- `LLMJudgeVerifier` — uses LLM to score output quality (SCORE/VERDICT/REASON format), configurable threshold
- `GroundTruthVerifier` — exact, substring, and Jaccard word-overlap comparison against a reference
- `VerifierPipeline` — runs multiple verifiers with `ALL_PASS`, `ANY_PASS`, or `THRESHOLD` aggregation modes
- `FakeVerifier` updated: `feedback` param, import moved to `uaaf.cognitive.verifier`
- Contract tests for all 4 verifiers (`test_verifier_contract.py`)
- Integration smoke: `EvaluatorOptimizerStrategy` + `VerifierPipeline` end-to-end (`test_phase2_smoke.py`)

### CI gate (Phase 2 complete)
- `ruff check`: 0 violations
- `mypy uaaf/`: 0 errors (39 source files)
- `pytest --cov=uaaf`: 245 passed, 1 skipped, coverage **90.21%** (gate: 85%)

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
- `mypy uaaf/`: 0 errors (33 source files)
- `pytest --cov=uaaf`: 192 passed, 1 skipped, coverage **88.77%** (gate: 85%)

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
- `uaaf._testing` public test utilities (`FakeLLMProvider`, `FakeKnowledgeBackbone`, pytest fixtures)

### CI gate (Phase 0 complete)
- `ruff check`: 0 violations
- `mypy uaaf/`: 0 errors (22 source files)
- `pytest --cov=uaaf`: 114 passed, 1 skipped, coverage **87.18%** (gate: 85%)
