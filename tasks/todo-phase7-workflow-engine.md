# Phase 7 — Workflow Engine + State Machine + Checkpoint: Task List

> Chi tiết: `tasks/plan.md`
> CI gate đầu vào: 487 tests pass, ruff ✓, mypy ✓, 87.77% coverage
> Pattern reference: `uaaf/knowledge/`

---

## Phase A: Protocols + Foundation

- [ ] **P7-T01** — `uaaf/workflow/checkpoint.py` + `uaaf/workflow/stores/in_memory.py`: ICheckpointStore Protocol + Checkpoint dataclass + InMemoryCheckpointStore
  - Files: `uaaf/workflow/__init__.py`, `uaaf/workflow/checkpoint.py`, `uaaf/workflow/stores/__init__.py`, `uaaf/workflow/stores/in_memory.py`, `tests/unit/workflow/__init__.py`, `tests/unit/workflow/test_checkpoint.py`
  - Gate: `pytest tests/unit/workflow/test_checkpoint.py` → 8+ pass; mypy 0 errors

- [ ] **P7-T02** — `uaaf/workflow/state_machine.py`: IState Protocol + Workflow dataclass + StateMachine + StateTransition
  - Files: `uaaf/workflow/state_machine.py`, `tests/unit/workflow/test_state_machine.py`
  - Gate: `pytest tests/unit/workflow/test_state_machine.py` → 7+ pass

### ✅ Checkpoint A
```
pytest tests/unit/workflow/                            → 15+ pass
mypy uaaf/workflow/                                    → 0 errors
ruff check uaaf/workflow/ tests/unit/workflow/         → 0 violations
```

---

## Phase B: Engine Core

- [ ] **P7-T03** — `uaaf/workflow/engine.py`: IWorkflowEngine Protocol + WorkflowEngine.run() + WorkflowResult + WorkflowStatus + tiered error handling (Retryable/Degraded/Fatal)
  - Files: `uaaf/workflow/engine.py`, `tests/unit/workflow/test_engine_run.py`
  - Gate: `pytest tests/unit/workflow/test_engine_run.py` → 12+ pass; covers happy path, RetryableError retry, FatalError, DegradedError, max_transitions cap

- [ ] **P7-T04** — `WorkflowEngine.resume()` SIGKILL-safe recovery + refactor `run()` để share inner loop
  - Files: `uaaf/workflow/engine.py` (extend), `tests/unit/workflow/test_engine_resume.py`
  - Gate: `pytest tests/unit/workflow/test_engine_resume.py` → 8+ pass; covers each-state resume, no-checkpoint, post-terminal, broken next_state

### ✅ Checkpoint B — Human review required before Phase C
```
pytest tests/unit/workflow/                            → 35+ pass
mypy uaaf/                                              → 0 errors
ruff check uaaf/ tests/                                → 0 violations
coverage uaaf/workflow/engine.py                       → ≥ 90%
coverage uaaf/workflow/state_machine.py                → ≥ 90%
```

---

## Phase C: Persistence + Contract Tests

- [ ] **P7-T05** — `uaaf/workflow/stores/file.py`: FileCheckpointStore (JSON-on-disk, atomic write tmpfile→rename, raise FatalError on non-serializable output)
  - Files: `uaaf/workflow/stores/file.py`, `tests/unit/workflow/stores/__init__.py`, `tests/unit/workflow/stores/test_file.py`
  - Gate: `pytest tests/unit/workflow/stores/test_file.py` → 10+ pass; cross-process simulation works

- [ ] **P7-T06** — `tests/contract/test_workflow_contract.py`: parametric contract tests cho ICheckpointStore (in_memory + file) + IWorkflowEngine
  - Files: `tests/contract/test_workflow_contract.py`
  - Gate: `pytest tests/contract/test_workflow_contract.py -v` → all pass với cả 2 store impls

### ✅ Checkpoint C
```
pytest tests/                                          → 525+ pass
mypy uaaf/ tests/                                      → 0 errors
ruff check uaaf/ tests/                                → 0 violations
coverage uaaf/workflow/                                → ≥ 90%
```

---

## Phase D: Public API + Test Utilities + Ship

- [ ] **P7-T07** — `uaaf/_testing/fakes.py`: FakeCheckpointStore + FakeWorkflowEngine cho product-side tests
  - Files: `uaaf/_testing/fakes.py` (extend), `tests/unit/_testing/test_workflow_fakes.py`
  - Gate: `pytest tests/unit/_testing/test_workflow_fakes.py` → 6+ pass; isinstance Protocol checks pass

- [ ] **P7-T08** — Integration smoke test + public API exports + version bump 0.1.0b6 → 0.1.0b7 + CHANGELOG + project memory
  - Files: `tests/integration/test_phase7_smoke.py`, `uaaf/__init__.py`, `pyproject.toml`, `CHANGELOG.md`, `memory/project_phase7_status.md`
  - Gate: `from uaaf import WorkflowEngine, Workflow, IState, ICheckpointStore, FileCheckpointStore` → no ImportError

### ✅ Final CI Gate — Phase 7 Complete
```
ruff check uaaf/ tests/ examples/                      → 0 violations
mypy uaaf/                                              → 0 errors
pytest tests/ --cov=uaaf --cov-fail-under=88           → 530+ pass, ≥88% coverage ✅
python -c "from uaaf import WorkflowEngine, Workflow, IState, ICheckpointStore, FileCheckpointStore"   → no ImportError ✅
grep -r "asyncio.gather" uaaf/                         → no results ✅
grep -r "import asyncio" uaaf/workflow/                → no results ✅
```

---

## New Files Summary

| File | Type | Est. Lines |
|------|------|-----------|
| `uaaf/workflow/__init__.py` | new | 0 |
| `uaaf/workflow/checkpoint.py` | new | ~50 |
| `uaaf/workflow/state_machine.py` | new | ~100 |
| `uaaf/workflow/engine.py` | new | ~200 |
| `uaaf/workflow/stores/__init__.py` | new | 0 |
| `uaaf/workflow/stores/in_memory.py` | new | ~50 |
| `uaaf/workflow/stores/file.py` | new | ~100 |
| `tests/unit/workflow/**` | new (7 files) | ~880 |
| `tests/contract/test_workflow_contract.py` | new | ~200 |
| `tests/unit/_testing/test_workflow_fakes.py` | new | ~80 |
| `tests/integration/test_phase7_smoke.py` | new | ~150 |
| `uaaf/_testing/fakes.py` | modify | +60 |
| `uaaf/__init__.py` | modify | +12 exports |
| `pyproject.toml` | modify | version |
| `CHANGELOG.md` | modify | +entry |
| `memory/project_phase7_status.md` | new | small |

**Total**: ~500 LOC prod code + ~1310 LOC test code (test/code ratio ~2.6x).

---

## Parallelization

- **Strict sequential**: T01 → T02 → T03 → T04
- **Parallel sau Checkpoint B**: T05 ⇄ T07 (independent), T06 cần T05
- **T08 cuối**: requires all prior

---

## Status

**Plan ready**. Awaiting human approval trước khi T01 bắt đầu.
