# Phase 8.1 — Workflow as Independent Library — TODO

> **Approach:** Workflow is a fully independent PyPI library `uaaf-workflow` with top-level `uaaf_workflow` namespace.
> **Clean break:** No shims, no top-level re-exports from `uaaf`. Tests/examples/docs migrate to new imports.
>
> See `plan-phase8-modular-packaging.md` for full context.

---

## Phase 8.1.A — Skeleton + Migration Plan (non-destructive)

- [x] **T01** Create `packages/uaaf-workflow/{src/uaaf_workflow/, pyproject.toml, README.md, LICENSE}` skeleton
- [x] **T02** Write `packages/MIGRATION.md` (sed map + deletion list)
- [x] **T03** Add CHANGELOG.md v0.2.0a1 UNRELEASED entry (BREAKING)

**Checkpoint 8.1.A** — skeleton present, `pytest -x` still green

---

## Phase 8.1.B — Build `uaaf-workflow` library ⚠️ ARCH RISK

- [x] **T04** Copy 9 files → `packages/uaaf-workflow/src/uaaf_workflow/...` (7 workflow + errors.py + context.py)
- [x] **T05** Rewrite imports inside copied files (`from uaaf.*` → `from uaaf_workflow.*`)
- [x] **T06** Write `uaaf_workflow/__init__.py` with curated re-exports
- [x] **T07** Fill `packages/uaaf-workflow/pyproject.toml` (anyio + py.typed); build wheel; verify wheel contents via `unzip -l`

**Checkpoint 8.1.B** — wheel builds cleanly, importable in isolated venv. **STOP for human review.**

---

## Phase 8.1.C — Delete originals + update internal UAAF imports

- [x] **T08** Delete `uaaf/workflow/` (dir), `uaaf/observability/errors.py`, `uaaf/runtime/context.py`
- [x] **T09** Update 16 internal `uaaf/` files per migration map (apply sed)
- [x] **T10** Strip workflow + errors + context re-exports from `uaaf/__init__.py`; update `__all__`
- [x] **T11** Root `pyproject.toml`: bump to 0.2.0a1, add `uaaf-workflow>=0.2.0a1` dep, remove direct `anyio`
- [x] **T12** Write `scripts/install-dev.sh` (editable install of both packages)

**Checkpoint 8.1.C** — both packages coexist in dev env; internal imports clean

---

## Phase 8.1.D — Migrate external callsites + verify

- [x] **T13** Apply sed migration to `tests/`, `examples/`, `conftest.py`, `uaaf/_testing/`
- [x] **T14** Migrate top-level `from uaaf import {workflow-symbols}` in tests/examples/docs (manual — mixed symbol lines)
- [x] **T15** Apply sed migration to `docs/` `.md` files (code snippets)
- [ ] **T16** Fix pre-existing obs 2646 runbook section 12 snippet (gets killed alongside T15) — still failing, deferred to Phase 8.1.E
- [x] **T17** Remove `__version__` references; switch to `importlib.metadata`
- [x] **T18** Full local CI gate: 604 pass, 2 pre-existing doc failures only

**Checkpoint 8.1.D** — 604 tests green, zero stale imports, mypy clean

---

## Phase 8.1.E — Isolation test + CI + release prep

- [x] **T19** Write `scripts/test-workflow-isolation.sh` (fresh venv + assert `import uaaf` fails)
- [x] **T20** Update `.github/workflows/ci.yml`: add `workflow-isolation` job
- [x] **T21** Update root `README.md` install section
- [x] **T22** Write `packages/uaaf-workflow/README.md` (standalone framing + quickstart)
- [x] **T23** Verify version pin consistency (root + workflow pyproject.toml + CHANGELOG)
- [x] **T24** Write `memory/project_phase8_status.md` + update MEMORY.md index

**Checkpoint 8.1 (FINAL)** — workflow is standalone, CI proves isolation, tag v0.2.0a1 ready

---

## Migration map (quick reference, full in `packages/MIGRATION.md` after T02)

```
from uaaf.observability.errors  →  from uaaf_workflow.errors
from uaaf.runtime.context       →  from uaaf_workflow.context
from uaaf.workflow.engine       →  from uaaf_workflow.engine
from uaaf.workflow.state_machine→  from uaaf_workflow.state_machine
from uaaf.workflow.checkpoint   →  from uaaf_workflow.checkpoint
from uaaf.workflow.stores.*     →  from uaaf_workflow.stores.*
from uaaf.workflow              →  from uaaf_workflow

# Top-level `from uaaf import X` for workflow symbols → manual migration (mixed lines)
```

---

## Estimated effort

~8.5 hours / 1 working day for Phase 8.1.
