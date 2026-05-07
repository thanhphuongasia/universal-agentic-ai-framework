# Phase 6 — Multi-Agent Orchestration: Task List

> Chi tiết: `phase6-multi-agent-orchestration-plan.md`
> CI gate đầu vào: 383 tests pass, ruff ✓, mypy ✓, 91.48% coverage

---

## Phase A: AgentPool Foundation

- [ ] **P6-T01** — `uaaf/execution/pool.py`: AgentPool (register, dispatch, dispatch_to, fan_out via anyio)
  - Files: `uaaf/execution/pool.py`, `uaaf/execution/__init__.py`, `tests/unit/execution/test_pool.py`
  - Gate: `pytest tests/unit/execution/test_pool.py` → 18+ pass; mypy 0 errors

- [ ] **P6-T02** — Edge-case tests: exception propagation, empty pool, result ordering (N > max_concurrency)
  - Files: `tests/unit/execution/test_pool.py` (extend)
  - Gate: coverage `uaaf/execution/pool.py` ≥ 90%

### ✅ Checkpoint A
```
pytest tests/unit/execution/test_pool.py  → all pass
mypy uaaf/ && ruff check uaaf/ tests/    → clean
```

---

## Phase B: ParallelFanoutStrategy

- [ ] **P6-T03** — `uaaf/cognitive/strategies/parallel.py`: ParallelFanoutStrategy (ICognitiveStrategy #4)
  - Files: `uaaf/cognitive/strategies/parallel.py`, `uaaf/cognitive/strategies/__init__.py`, `tests/unit/cognitive/test_parallel.py`, `tests/contract/test_strategy_contract.py` (add to parametrize)
  - Gate: `pytest tests/unit/cognitive/test_parallel.py tests/contract/test_strategy_contract.py` → all pass

### ✅ Checkpoint B
```
pytest tests/                         → 395+ pass, no regression
mypy uaaf/ && ruff check uaaf/ tests/ → clean
```

---

## Phase C: OrchestratorAgent

- [ ] **P6-T04** — `uaaf/execution/orchestrator.py`: OrchestratorAgent (BaseAgent, LLM decompose → fan_out → synthesize)
  - Files: `uaaf/execution/orchestrator.py`, `uaaf/execution/__init__.py`, `tests/unit/execution/test_orchestrator.py`
  - Gate: `pytest tests/unit/execution/test_orchestrator.py` → 12+ pass; mypy 0 errors

- [ ] **P6-T05** — `tests/integration/test_phase6_smoke.py`: end-to-end (OrchestratorAgent → AgentPool → 3 FakeWorkers → cost agg)
  - Files: `tests/integration/test_phase6_smoke.py`
  - Gate: smoke test pass, no flaky

### ✅ Checkpoint C — Human review required before Phase D
```
pytest tests/                                       → 420+ pass, 0 failed
mypy uaaf/                                          → 0 errors
ruff check uaaf/ tests/                            → 0 violations
coverage uaaf/execution/pool.py                    → ≥ 90%
coverage uaaf/execution/orchestrator.py            → ≥ 85%
coverage uaaf/cognitive/strategies/parallel.py     → ≥ 85%
```

---

## Phase D: Refactor + Housekeeping

- [ ] **P6-T06** — `examples/code_analysis/agents.py`: replace `asyncio.gather` → `AgentPool.fan_out`
  - Gate: `grep -r "asyncio.gather" examples/` → no results

- [ ] **P6-T07** — `uaaf/_testing/fakes.py`: add `FakeAgentPool.fan_out()` method
  - Gate: `pytest tests/unit/_testing/` → pass

- [ ] **P6-T08** — CHANGELOG v0.1.0b6 + `uaaf/__init__.py` exports + project memory
  - Gate: `from uaaf import AgentPool, OrchestratorAgent` → no ImportError

### ✅ Final CI Gate — Phase 6 Complete
```
ruff check uaaf/ tests/ examples/                      → 0 violations
mypy uaaf/ examples/                                   → 0 errors
pytest tests/ --cov=uaaf --cov-fail-under=88           → ≥ 420 pass, ≥ 88% coverage
grep -r "asyncio.gather" uaaf/                         → no results
python -c "from uaaf import AgentPool, OrchestratorAgent"  → no ImportError
```

---

## New Files Summary

| File | Type | Est. Lines |
|------|------|-----------|
| `uaaf/execution/pool.py` | new | ~80 |
| `uaaf/execution/orchestrator.py` | new | ~100 |
| `uaaf/cognitive/strategies/parallel.py` | new | ~70 |
| `tests/unit/execution/test_pool.py` | new | ~140 |
| `tests/unit/execution/test_orchestrator.py` | new | ~120 |
| `tests/unit/cognitive/test_parallel.py` | new | ~100 |
| `tests/integration/test_phase6_smoke.py` | new | ~80 |
| `uaaf/_testing/fakes.py` | modify | +15 |
| `examples/code_analysis/agents.py` | modify | surgical |
| `uaaf/execution/__init__.py` | modify | +2 exports |
| `uaaf/cognitive/strategies/__init__.py` | modify | +1 export |
| `uaaf/__init__.py` | modify | +2 exports |
| `CHANGELOG.md` | modify | +1 entry |
