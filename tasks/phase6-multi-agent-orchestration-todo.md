# Phase 6 — Multi-Agent Orchestration: Task List

> Chi tiết: `phase6-multi-agent-orchestration-plan.md`
> CI gate đầu vào: 383 tests pass, ruff ✓, mypy ✓, 91.48% coverage
> **OrchestratorAgent removed (Fix #5)** — xem Resolved Decisions trong plan.

---

## Phase A: AgentPool Foundation

- [ ] **P6-T01** — `uaaf/execution/pool.py`: AgentPool (register, dispatch round_robin/random, dispatch_to, fan_out fail_fast/collect via anyio)
  - Files: `uaaf/execution/pool.py`, `uaaf/execution/__init__.py`, `tests/unit/execution/test_pool.py`
  - Gate: `pytest tests/unit/execution/test_pool.py` → 20+ pass; mypy 0 errors

- [ ] **P6-T02** — Edge-case tests: on_error modes, exception propagation, round_robin cycle, rate-limiter deadlock
  - Files: `tests/unit/execution/test_pool.py` (extend)
  - Gate: coverage `uaaf/execution/pool.py` ≥ 90%

### ✅ Checkpoint A
```
pytest tests/unit/execution/test_pool.py  → all pass
mypy uaaf/ && ruff check uaaf/ tests/    → clean
```

---

## Phase B: ParallelFanoutStrategy

- [ ] **P6-T03** — `uaaf/cognitive/strategies/parallel.py`: ISubtaskBuilder Protocol + EntitySubtaskBuilder + ParallelFanoutStrategy (ICognitiveStrategy #4, dùng fan_out on_error="collect")
  - Files: `uaaf/cognitive/strategies/parallel.py`, `uaaf/cognitive/strategies/__init__.py`, `tests/unit/cognitive/test_parallel.py`, `tests/contract/test_strategy_contract.py` (add to parametrize)
  - Gate: `pytest tests/unit/cognitive/test_parallel.py tests/contract/test_strategy_contract.py` → all pass

### ✅ Checkpoint B — Human review required before Phase C
```
pytest tests/                         → 395+ pass, no regression
mypy uaaf/ && ruff check uaaf/ tests/ → clean
coverage uaaf/execution/pool.py       → ≥ 90%
coverage uaaf/cognitive/strategies/parallel.py → ≥ 85%
```

---

## Phase C: Refactor + Housekeeping

- [ ] **P6-T06** — `examples/code_analysis/agents.py`: replace `asyncio.gather` → `AgentPool.fan_out`
  - Gate: `grep -r "asyncio.gather" examples/` → no results; `grep -r "import asyncio" examples/code_analysis/agents.py` → no results

- [ ] **P6-T07** — `uaaf/_testing/fakes.py`: add `FakeAgentPool.fan_out(tasks, context, on_error)` method
  - Gate: `pytest tests/unit/_testing/` → pass

- [ ] **P6-T08** — CHANGELOG v0.1.0b6 + `uaaf/__init__.py` exports + project memory
  - Gate: `from uaaf import AgentPool` + `from uaaf.cognitive.strategies import ParallelFanoutStrategy` → no ImportError

### ✅ Final CI Gate — Phase 6 Complete
```
ruff check uaaf/ tests/ examples/                      → 0 violations
mypy uaaf/ examples/                                   → 0 errors
pytest tests/ --cov=uaaf --cov-fail-under=88           → ≥ 395 pass, ≥ 88% coverage
grep -r "asyncio.gather" uaaf/                         → no results
grep -r "asyncio.gather" examples/code_analysis/       → no results
python -c "from uaaf import AgentPool"                 → no ImportError
python -c "from uaaf.cognitive.strategies import ParallelFanoutStrategy"  → no ImportError
```

---

## New Files Summary

| File | Type | Est. Lines |
|------|------|-----------|
| `uaaf/execution/pool.py` | new | ~100 |
| `uaaf/cognitive/strategies/parallel.py` | new | ~90 |
| `tests/unit/execution/test_pool.py` | new | ~140 |
| `tests/unit/cognitive/test_parallel.py` | new | ~110 |
| `uaaf/_testing/fakes.py` | modify | +15 |
| `examples/code_analysis/agents.py` | modify | surgical |
| `uaaf/execution/__init__.py` | modify | +1 export |
| `uaaf/cognitive/strategies/__init__.py` | modify | +2 exports |
| `uaaf/__init__.py` | modify | +1 export |
| `CHANGELOG.md` | modify | +1 entry |

---

## Removed from scope

| Item | Lý do |
|------|-------|
| `uaaf/execution/orchestrator.py` | Duplicate với ParallelFanoutStrategy — Fix #5 |
| `tests/unit/execution/test_orchestrator.py` | Theo OrchestratorAgent |
| `tests/integration/test_phase6_smoke.py` | Theo OrchestratorAgent |
