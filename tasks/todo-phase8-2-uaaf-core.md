# Phase 8.2 — ryuu-core: Zero-Dep Foundation Package — TODO

> **Approach**: TDD — viết tests RED trước, implement GREEN, backward-compat qua re-exports.  
> **Key insight**: `ryuu_workflow.errors` + `ryuu_workflow.context` trở thành thin re-export — zero callsite migration.  
> See `plan-phase8-2-ryuu-core.md` for full context.

**STATUS: ALL TASKS COMPLETE ✅** — 637 tests GREEN, core-isolation PASSED

---

## Phase 8.2.A — Skeleton + Tests RED

- [x] **T01** Create `packages/ryuu-core/{src/ryuu_core/, pyproject.toml, README.md, LICENSE}` skeleton
- [x] **T02** Write `tests/unit/core/test_errors.py` (RED — `from ryuu_core.errors import ...`)
- [x] **T03** Write `tests/unit/core/test_context.py` (RED)
- [x] **T04** Write `tests/unit/core/test_models.py` (RED — Cost, Task, AgentResult, StructuredIntent, ...)
- [x] **T05** Write `tests/unit/core/test_protocols.py` + `tests/unit/core/test_nulls.py` (RED)

---

## Phase 8.2.B — Implement ryuu-core (GREEN)

- [x] **T06** Copy `errors.py` + `context.py` từ `ryuu_workflow` → `ryuu_core`, fix internal imports
- [x] **T07** Write `ryuu_core/models.py` — Cost, Task, AgentResult, StructuredIntent, CognitiveResult, CostEstimate, ComplexityLevel, ModelTier
- [x] **T08** Write `ryuu_core/protocols.py` — ICostTracker, ITracer, IAuditLogger, IRateLimiter
- [x] **T09** Write `ryuu_core/nulls.py` — NullCostTracker, NullTracer, NullAuditLogger, NullRateLimiter
- [x] **T10** Write `ryuu_core/__init__.py` with curated re-exports

---

## Phase 8.2.C — Wire ryuu-workflow → ryuu-core

- [x] **T11** Fill `packages/ryuu-core/pyproject.toml`: zero deps, build + verify wheel
- [x] **T12** Update `packages/ryuu-workflow/pyproject.toml`: add `ryuu-core>=0.2.0a1` dep
- [x] **T13** Replace `ryuu_workflow/errors.py` with thin re-export from `ryuu_core.errors`
- [x] **T14** Replace `ryuu_workflow/context.py` with thin re-export from `ryuu_core.context`

---

## Phase 8.2.D — Wire ryuu → ryuu-core + NullObject BaseAgent

- [x] **T15** `ryuu/observability/cost.py`: replace `Cost` definition with `from ryuu_core.models import Cost`
- [x] **T16** `ryuu/intent/models.py`: replace model definitions with re-imports from `ryuu_core.models`
- [x] **T17** `ryuu/execution/agent.py`: replace Task+AgentResult with re-imports; wire NullObject defaults into BaseAgent fields
- [x] **T18** Root `pyproject.toml`: add `ryuu-core>=0.2.0a1` dep
- [x] **T19** Full CI gate: pytest 637 GREEN, mypy clean

---

## Phase 8.2.E — Isolation + CI + Docs

- [x] **T20** Write `scripts/test-core-isolation.sh` (fresh venv, proves `import ryuu` fails)
- [x] **T21** Update `.github/workflows/ci.yml`: add `core-isolation` job
- [x] **T22** Update `packages/MIGRATION.md` Phase 8.2 section
- [x] **T23** Update `CHANGELOG.md` v0.2.0a1 with Phase 8.2 changes
- [x] **T24** Update memory + MEMORY.md index

---

## Quick reference — new import paths (canonical)

```
ryuu_core.errors     →  RetryableError, DegradedError, FatalError, BudgetExceededError, ...
ryuu_core.context    →  ExecutionContext, ContextScope
ryuu_core.models     →  Cost, Task, AgentResult, StructuredIntent, CognitiveResult, ...
ryuu_core.protocols  →  ICostTracker, ITracer, IAuditLogger, IRateLimiter
ryuu_core.nulls      →  NullCostTracker, NullTracer, NullAuditLogger, NullRateLimiter

# Backward-compat (still works, but deprecated going forward):
ryuu_workflow.errors   →  re-exports from ryuu_core.errors
ryuu_workflow.context  →  re-exports from ryuu_core.context
ryuu.intent.models     →  re-exports from ryuu_core.models
ryuu.execution.agent   →  re-exports from ryuu_core.models (for Task, AgentResult)
```
