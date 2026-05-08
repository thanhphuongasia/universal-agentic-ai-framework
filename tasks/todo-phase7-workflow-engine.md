# Phase 7 — Workflow Engine + State Machine + Checkpoint: Task List

## Phase A — Checkpoint Protocol + InMemory Store

- [x] **T01** — `ICheckpointStore` Protocol + `Checkpoint` dataclass + `InMemoryCheckpointStore` + 12 unit tests (GREEN)

## Phase B — State Machine + Engine

- [x] **T02** — `IState` Protocol + `StateTransition` + `Workflow` + `StateMachine` + 12 unit tests (GREEN)
- [x] **T03** — `IWorkflowEngine` Protocol + `WorkflowResult` + `WorkflowStatus` + `WorkflowEngine.run()` skeleton (GREEN)
- [x] **T04** — Full `WorkflowEngine.run()`: retry/backoff, error tiers, checkpoint-per-state, max_transitions guard + 12 tests (GREEN)

## Phase C — FileCheckpointStore + Contract Tests

- [x] **T05** — `FileCheckpointStore` (JSON, atomic write, SIGKILL-safe) + 12 unit tests (GREEN)
- [x] **T06** — `WorkflowEngine.resume()` + contract tests parametrized over both stores + 7 resume tests (GREEN)

## Phase D — Fakes + Integration Smoke

- [x] **T07** — `FakeCheckpointStore` + `FakeWorkflowEngine` in `uaaf/_testing/fakes.py` + 12 unit tests (GREEN)
- [x] **T08** — Integration smoke test: 3-state pipeline + SIGKILL resume + public API assertions (GREEN)

## Phase E — Cognitive Pipeline Wiring

- [x] **T09** — `ExecutionContext` frozen + `strategy_id` field + `RequestHandler` + 10 tests (GREEN)
- [x] **T10** — `LLMAgent._react_loop()` (rename from `react_loop`) + `BaseAgent.enforce_cognitive_routing` guard + 3 tests (GREEN)

---

## Final CI Gate (v0.1.0b7)

- [x] 604 tests pass (+ 2 pre-existing doc failures, 1 skip)
- [x] Coverage 89.25% ≥ 88% threshold
- [x] mypy: no issues in 70 source files
- [x] ruff: 0 new errors (2 pre-existing unrelated)
- [x] `from uaaf import WorkflowEngine, Workflow, IState, ICheckpointStore, FileCheckpointStore` → OK
- [x] `grep -rn "\.react_loop("` → 0 results
- [x] `strategy_id` field in `ExecutionContext` ✓
