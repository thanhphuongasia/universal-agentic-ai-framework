# Phase 8.2 — uaaf-core: Zero-Dep Foundation Package — TODO

> **Approach**: TDD — viết tests RED trước, implement GREEN, backward-compat qua re-exports.  
> **Key insight**: `uaaf_workflow.errors` + `uaaf_workflow.context` trở thành thin re-export — zero callsite migration.  
> See `plan-phase8-2-uaaf-core.md` for full context.

---

## Phase 8.2.A — Skeleton + Tests RED

- [ ] **T01** Create `packages/uaaf-core/{src/uaaf_core/, pyproject.toml, README.md, LICENSE}` skeleton
- [ ] **T02** Write `tests/unit/core/test_errors.py` (RED — `from uaaf_core.errors import ...`)
- [ ] **T03** Write `tests/unit/core/test_context.py` (RED)
- [ ] **T04** Write `tests/unit/core/test_models.py` (RED — Cost, Task, AgentResult, StructuredIntent, ...)
- [ ] **T05** Write `tests/unit/core/test_protocols.py` + `tests/unit/core/test_nulls.py` (RED)

**Checkpoint 8.2.A** — Skeleton present, test files collect với ImportError (expected RED)

---

## Phase 8.2.B — Implement uaaf-core (GREEN)

- [ ] **T06** Copy `errors.py` + `context.py` từ `uaaf_workflow` → `uaaf_core`, fix internal imports
- [ ] **T07** Write `uaaf_core/models.py` — Cost, Task, AgentResult, StructuredIntent, CognitiveResult, CostEstimate, ComplexityLevel, ModelTier
- [ ] **T08** Write `uaaf_core/protocols.py` — ICostTracker, ITracer, IAuditLogger, IRateLimiter
- [ ] **T09** Write `uaaf_core/nulls.py` — NullCostTracker, NullTracer, NullAuditLogger, NullRateLimiter
- [ ] **T10** Write `uaaf_core/__init__.py` with curated re-exports

**Checkpoint 8.2.B** — All 5 new test files GREEN, `from uaaf_core import X` works

---

## Phase 8.2.C — Wire uaaf-workflow → uaaf-core

- [ ] **T11** Fill `packages/uaaf-core/pyproject.toml`: zero deps, build + verify wheel
- [ ] **T12** Update `packages/uaaf-workflow/pyproject.toml`: add `uaaf-core>=0.2.0a1` dep
- [ ] **T13** Replace `uaaf_workflow/errors.py` with thin re-export from `uaaf_core.errors`
- [ ] **T14** Replace `uaaf_workflow/context.py` with thin re-export from `uaaf_core.context`

**Checkpoint 8.2.C** — `from uaaf_workflow.errors import X` still works (backward-compat proven)

---

## Phase 8.2.D — Wire uaaf → uaaf-core + NullObject BaseAgent

- [ ] **T15** `uaaf/observability/cost.py`: replace `Cost` definition with `from uaaf_core.models import Cost`
- [ ] **T16** `uaaf/intent/models.py`: replace model definitions with re-imports from `uaaf_core.models`
- [ ] **T17** `uaaf/execution/agent.py`: replace Task+AgentResult with re-imports; wire NullObject defaults into BaseAgent fields
- [ ] **T18** Root `pyproject.toml`: add `uaaf-core>=0.2.0a1` dep
- [ ] **T19** Full CI gate: pytest (604+) green, mypy clean

**Checkpoint 8.2.D** — Full suite green, `BaseAgent(agent_id="x")` constructs with no args

---

## Phase 8.2.E — Isolation + CI + Docs

- [ ] **T20** Write `scripts/test-core-isolation.sh` (fresh venv, proves `import uaaf` fails)
- [ ] **T21** Update `.github/workflows/ci.yml`: add `core-isolation` job
- [ ] **T22** Update `packages/MIGRATION.md` Phase 8.2 section
- [ ] **T23** Update `CHANGELOG.md` v0.2.0a1 with Phase 8.2 changes
- [ ] **T24** Update memory + MEMORY.md index

**Checkpoint 8.2 FINAL** — uaaf-core standalone, uaaf-workflow backward-compat, CI green

---

## Quick reference — new import paths (canonical)

```
uaaf_core.errors     →  RetryableError, DegradedError, FatalError, BudgetExceededError, ...
uaaf_core.context    →  ExecutionContext, ContextScope
uaaf_core.models     →  Cost, Task, AgentResult, StructuredIntent, CognitiveResult, ...
uaaf_core.protocols  →  ICostTracker, ITracer, IAuditLogger, IRateLimiter
uaaf_core.nulls      →  NullCostTracker, NullTracer, NullAuditLogger, NullRateLimiter

# Backward-compat (still works, but deprecated going forward):
uaaf_workflow.errors   →  re-exports from uaaf_core.errors
uaaf_workflow.context  →  re-exports from uaaf_core.context
uaaf.intent.models     →  re-exports from uaaf_core.models
uaaf.execution.agent   →  re-exports from uaaf_core.models (for Task, AgentResult)
```
