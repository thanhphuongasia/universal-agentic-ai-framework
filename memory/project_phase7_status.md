---
name: RYUU Phase 7 status
description: Phase 7 Workflow Engine — implementation progress, files created, remaining tasks
type: project
---

# RYUU Phase 7 — Workflow Engine + State Machine + Checkpoint

**Status**: In progress — 2026-05-08  
**Why:** Batch mode for Code Analysis, Flashcard, Stock trading, AI coding practice products.  
**How to apply:** Resume from here. T07 tests + T08 + Phase E (T09, T10) remain.

---

## CI Gate vào (Phase 6)
- 492 tests pass, 88.02% coverage, ruff ✓, mypy ✓, v0.1.0b6

## Tiến độ hiện tại

### ✅ Phase A — Protocols + Foundation
- **T01** DONE: `ryuu/workflow/checkpoint.py` (Checkpoint, ICheckpointStore, make_checkpoint) + `ryuu/workflow/stores/in_memory.py` (InMemoryCheckpointStore) + 12 tests
- **T02** DONE: `ryuu/workflow/state_machine.py` (IState, StateTransition, Workflow, StateMachine) + 12 tests

### ✅ Phase B — Engine Core
- **T03** DONE: `ryuu/workflow/engine.py` (WorkflowStatus, WorkflowResult, IWorkflowEngine, WorkflowEngine.run()) + 12 tests
- **T04** DONE: `WorkflowEngine.resume()` in same file + 7 tests

### ✅ Phase C — Persistence + Contract Tests
- **T05** DONE: `ryuu/workflow/stores/file.py` (FileCheckpointStore, atomic write) + 12 tests
- **T06** DONE: `tests/contract/test_workflow_contract.py` — 20 parametric tests (in_memory + file)

### 🔄 Phase D — Public API + Test Utilities + Ship (IN PROGRESS)
- **T07** PARTIAL: `FakeCheckpointStore` + `FakeWorkflowEngine` added to `ryuu/_testing/fakes.py` (lines ~240+). Tests NOT yet written.
  - Remaining: `tests/unit/_testing/test_workflow_fakes.py` (6+ tests)
- **T08** NOT STARTED: integration smoke + public API exports + version bump + CHANGELOG

### ❌ Phase E — Cognitive Pipeline Wiring
- **T09** NOT STARTED: `ExecutionContext` frozen + `strategy_id` field + `RequestHandler`
- **T10** NOT STARTED: `_react_loop()` rename + `enforce_cognitive_routing` + examples migrate

---

## Số liệu hiện tại
- 569 tests pass (+ 2 pre-existing doc failures, 1 skip) — 75 mới từ Phase 7
- mypy ryuu/workflow/ → 0 errors
- ruff → clean (sau auto-fix)
- workflow coverage: 97.55%

## Files đã tạo (Phase 7)
```
ryuu/workflow/__init__.py
ryuu/workflow/checkpoint.py
ryuu/workflow/state_machine.py
ryuu/workflow/engine.py
ryuu/workflow/stores/__init__.py
ryuu/workflow/stores/in_memory.py
ryuu/workflow/stores/file.py
tests/unit/workflow/__init__.py
tests/unit/workflow/test_checkpoint.py
tests/unit/workflow/test_state_machine.py
tests/unit/workflow/test_engine_run.py
tests/unit/workflow/test_engine_resume.py
tests/unit/workflow/stores/__init__.py
tests/unit/workflow/stores/test_file.py
tests/contract/test_workflow_contract.py
```

## Files đã modify
```
ryuu/_testing/fakes.py  (+ FakeCheckpointStore, FakeWorkflowEngine ~60 lines)
```

## Còn lại
1. `tests/unit/_testing/test_workflow_fakes.py` — 6+ tests cho T07
2. `tests/integration/test_phase7_smoke.py` — end-to-end smoke (T08)
3. `ryuu/__init__.py` — +12 exports (T08)
4. `pyproject.toml` — version bump 0.1.0b6 → 0.1.0b7 (T08)
5. `CHANGELOG.md` — entry (T08)
6. `ryuu/runtime/context.py` — frozen=True + strategy_id (T09)
7. `ryuu/runtime/request_handler.py` — new (T09)
8. `tests/unit/runtime/test_request_handler.py` — new (T09)
9. `ryuu/execution/llm_agent.py` — rename react_loop → _react_loop (T10)
10. `ryuu/execution/agent.py` — enforce_cognitive_routing flag (T10)
11. `examples/todo_app/agent.py`, `examples/stock_advisory/agent.py` — rename call (T10)

## Key design decisions ghi nhớ
- `terminal_states` = explicit end-markers (KHÔNG được run). States kết thúc tự nhiên qua `StateTransition(next_state=None)` VẪN được run + checkpointed.
- `final_state` trong WorkflowResult = `current_state or last_executed_state` để handle None case.
- DegradedError từ state → log warning + FAILED gracefully (không raise exception).
- `FileCheckpointStore`: JSON-only output; FatalError nếu không serializable.
