# Phase 6 — Multi-Agent Orchestration: Task List

> Chi tiết: `phase6-multi-agent-orchestration-plan.md`
> CI gate đầu vào: 383 tests pass, ruff ✓, mypy ✓, 91.48% coverage
> **OrchestratorAgent removed (Fix #5)** — xem Resolved Decisions trong plan.

---

## Phase A: AgentPool Foundation

- [x] **P6-T01** — `ryuu/execution/pool.py`: AgentPool (register, dispatch round_robin/random, dispatch_to, fan_out fail_fast/collect via anyio)
  - Files: `ryuu/execution/pool.py`, `ryuu/execution/__init__.py`, `tests/unit/execution/test_pool.py`
  - Gate: `pytest tests/unit/execution/test_pool.py` → 20+ pass; mypy 0 errors

- [x] **P6-T02** — Edge-case tests: on_error modes, exception propagation, round_robin cycle, rate-limiter deadlock
  - Files: `tests/unit/execution/test_pool.py` (extend)
  - Gate: coverage `ryuu/execution/pool.py` ≥ 90%

### ✅ Checkpoint A
```
pytest tests/unit/execution/test_pool.py  → all pass
mypy ryuu/ && ruff check ryuu/ tests/    → clean
```

---

## Phase B: ParallelFanoutStrategy

- [x] **P6-T03** — `ryuu/cognitive/strategies/parallel.py`: ISubtaskBuilder Protocol + EntitySubtaskBuilder + ParallelFanoutStrategy (ICognitiveStrategy #4, dùng fan_out on_error="collect")
  - Files: `ryuu/cognitive/strategies/parallel.py`, `ryuu/cognitive/strategies/__init__.py`, `tests/unit/cognitive/test_parallel.py`, `tests/contract/test_strategy_contract.py` (add to parametrize)
  - Gate: `pytest tests/unit/cognitive/test_parallel.py tests/contract/test_strategy_contract.py` → all pass

### ✅ Checkpoint B — Human review required before Phase C
```
pytest tests/                         → 395+ pass, no regression
mypy ryuu/ && ruff check ryuu/ tests/ → clean
coverage ryuu/execution/pool.py       → ≥ 90%
coverage ryuu/cognitive/strategies/parallel.py → ≥ 85%
```

---

## Phase C: Refactor + Housekeeping

- [x] **P6-T06** — `examples/code_analysis/agents.py`: replace `asyncio.gather` → `AgentPool.fan_out`
  - Gate: `grep -r "asyncio.gather" examples/` → no results; `grep -r "import asyncio" examples/code_analysis/agents.py` → no results

- [x] **P6-T07** — `ryuu/_testing/fakes.py`: add `FakeAgentPool.fan_out(tasks, context, on_error)` method
  - Gate: `pytest tests/unit/_testing/` → pass

- [x] **P6-T08** — CHANGELOG v0.1.0b6 + `ryuu/__init__.py` exports + project memory
  - Gate: `from ryuu import AgentPool` + `from ryuu.cognitive.strategies import ParallelFanoutStrategy` → no ImportError

### ✅ Final CI Gate — Phase 6 Complete
```
ruff check ryuu/ tests/ examples/                      → 0 violations
mypy ryuu/ examples/                                   → 0 errors
pytest tests/ --cov=ryuu --cov-fail-under=88           → 492 pass, 88.02% coverage ✅
grep -r "asyncio.gather" ryuu/                         → no results ✅
grep -r "asyncio.gather" examples/code_analysis/       → no results ✅
python -c "from ryuu import AgentPool"                 → no ImportError ✅
python -c "from ryuu.cognitive.strategies import ParallelFanoutStrategy"  → no ImportError ✅
```

---

## New Files Summary

| File | Type | Est. Lines |
|------|------|-----------|
| `ryuu/execution/pool.py` | new | ~130 |
| `ryuu/cognitive/strategies/parallel.py` | new | ~125 |
| `tests/unit/execution/test_pool.py` | new | ~356 |
| `tests/unit/cognitive/test_parallel.py` | new | ~289 |
| `ryuu/_testing/fakes.py` | modify | +15 |
| `examples/code_analysis/agents.py` | modify | surgical |
| `ryuu/execution/__init__.py` | modify | +1 export |
| `ryuu/cognitive/strategies/__init__.py` | modify | +6 exports |
| `ryuu/__init__.py` | modify | +1 export, version bump |
| `CHANGELOG.md` | modify | +1 entry |
| `docs/patterns/` | new | 6 files, ~1051 lines |

---

## Removed from scope

| Item | Lý do |
|------|-------|
| `ryuu/execution/orchestrator.py` | Duplicate với ParallelFanoutStrategy — Fix #5 |
| `tests/unit/execution/test_orchestrator.py` | Theo OrchestratorAgent |
| `tests/integration/test_phase6_smoke.py` | Theo OrchestratorAgent |
