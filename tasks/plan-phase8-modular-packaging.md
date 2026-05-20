# Phase 8 — Modular Packaging: Workflow as Independent Library

> **Architecture (chosen 2026-05-12):** `uaaf-workflow` is a **fully independent PyPI library** with its own top-level namespace `uaaf_workflow`. It is NOT a sub-package of `uaaf`. The AI framework `uaaf` depends on `uaaf-workflow` like any third-party library (e.g. anyio, pydantic).
>
> **Clean break:** No shim files in `uaaf/`. No back-compat re-exports for workflow symbols in `uaaf/__init__.py`. Consumers who used `from uaaf import WorkflowEngine` must migrate to `from uaaf_workflow.engine import WorkflowEngine`.
>
> **Scope (Phase 8.1):** Workflow extraction only. Cognitive wheel extraction is NOT in scope.

## 0. Mối quan hệ với UAAF v2 Architecture

Plan này là **bước đi đầu tiên** (proof-of-concept) của lộ trình tách package mô tả trong [`docs/architecture/uaaf-v2-architecture.md`](../docs/architecture/uaaf-v2-architecture.md). Hai doc đang **bổ sung** cho nhau, không mâu thuẫn:

| Doc | Vai trò | Scope |
|---|---|---|
| `uaaf-v2-architecture.md` §2-§4 | **Target state** — 13 packages cuối cùng | Strategic — toàn bộ refactor |
| `plan-phase8-modular-packaging.md` (file này) | **Phase 8.1** — tách 1 package (workflow) | Tactical — bước đầu, prove clean-break pattern |

**Khác biệt scope quan trọng**:
- v2 §4 đặt workflow trong namespace `uaaf.workflow.*` (sub-namespace).
- Plan 8.1 quyết định đặt workflow trong namespace `uaaf_workflow.*` (top-level riêng).
- **Lý do giữ quyết định 8.1**: Workflow muốn dùng được độc lập cho non-AI consumer (Wyckoff bot, ingestion pipeline). Namespace top-level `uaaf_workflow` rõ ràng hơn `uaaf.workflow.*`. Khi các package khác trong v2 được tách, chúng có thể chọn sub-namespace `uaaf.cognitive.*` vì luôn gắn với AI framework — không nhất quán với workflow là **chủ ý**.

**Phase 8.x roadmap** (đề xuất, sau khi 8.1 xong):
| Phase | Tách package | Tham chiếu v2 |
|---|---|---|
| **8.1** | `uaaf-workflow` (file này) | v2 §4 — adjust namespace lên `uaaf_workflow` |
| **8.2** | `uaaf-guardrail` (rule-based filters) | v2 §6 — Phase 2 content |
| **8.3** | `uaaf-knowledge-{core,stores,rag,memory}` (4 sub-packages) | v2 §4 — split god package |
| **8.4** | `uaaf-execution` tách khỏi `uaaf-runtime` | v2 §3 — runtime thành facade thuần |
| **8.5** | `uaaf-eval` | v2 §8 — dev dependency |

Mỗi Phase 8.x sẽ có plan riêng theo template của file này. Phase 8.1 xác lập **pattern** (build → delete → migrate → verify isolation), các phase sau lặp lại.

## 1. Goal

Make workflow a standalone library so consumers that need only the state-machine kernel (Wyckoff bots, ingestion pipelines, code analysis pipelines, generic DAG frameworks) can install it without touching UAAF's AI tier:

```bash
pip install uaaf-workflow         # standalone — only anyio dep
pip install uaaf                  # AI framework — auto-pulls uaaf-workflow
```

## 2. Confirmed Decisions

| # | Decision | Choice |
|---|---|---|
| 1 | Workflow lives where? | **Independent library `uaaf_workflow`** (top-level, NOT inside `uaaf/`) |
| 2 | Top-level `from uaaf import X` for workflow symbols | **Drop entirely (clean break)** |
| 3 | Version bump | **0.2.0a1** for both packages |
| 4 | `uaaf.__version__` accessor | Drop; use `importlib.metadata.version("uaaf")` or `version("uaaf-workflow")` |
| 5 | CHANGELOG | Single root CHANGELOG.md |
| 6 | Shim files in `uaaf/workflow/`, `uaaf/observability/errors.py`, `uaaf/runtime/context.py` | **NONE — files deleted entirely** |

## 3. Non-Goals

- ✋ Generalize `ExecutionContext` (remove `strategy_id` AI-specific field). Workflow-only consumers tolerate the field. Tracked as design debt.
- ✋ Separate git repo for workflow. Single monorepo, two PyPI packages.
- ✋ Move AI tier (cognitive/execution/intent/...) to a separate wheel. UAAF stays as one wheel. Cognitive split là **Phase 8.2-8.5** (xem §0, theo v2 architecture).
- ✋ Deprecation period with `DeprecationWarning`. UAAF is still beta — clean break is acceptable.
- ✋ Tách `uaaf-guardrail` / `uaaf-knowledge-*` / `uaaf-execution` / `uaaf-eval`. Tất cả là phase sau (xem §0 roadmap).
- ✋ Áp dụng full v2 namespace (`uaaf.cognitive.*` thay `uaaf_workflow.*`). Phase 8.1 cố ý dùng top-level `uaaf_workflow` cho workflow vì nó standalone-friendly. Các package khác trong Phase 8.2+ sẽ theo `uaaf.<tier>.*` per v2 §4.

## 4. Migration Audit (verified 2026-05-12)

### 4.1 Files moving FROM `uaaf/` TO `packages/uaaf-workflow/src/uaaf_workflow/`

| Old path | New path |
|---|---|
| `uaaf/workflow/__init__.py` | `packages/uaaf-workflow/src/uaaf_workflow/__init__.py` |
| `uaaf/workflow/engine.py` | `packages/uaaf-workflow/src/uaaf_workflow/engine.py` |
| `uaaf/workflow/state_machine.py` | `packages/uaaf-workflow/src/uaaf_workflow/state_machine.py` |
| `uaaf/workflow/checkpoint.py` | `packages/uaaf-workflow/src/uaaf_workflow/checkpoint.py` |
| `uaaf/workflow/stores/__init__.py` | `packages/uaaf-workflow/src/uaaf_workflow/stores/__init__.py` |
| `uaaf/workflow/stores/in_memory.py` | `packages/uaaf-workflow/src/uaaf_workflow/stores/in_memory.py` |
| `uaaf/workflow/stores/file.py` | `packages/uaaf-workflow/src/uaaf_workflow/stores/file.py` |
| `uaaf/observability/errors.py` | `packages/uaaf-workflow/src/uaaf_workflow/errors.py` |
| `uaaf/runtime/context.py` | `packages/uaaf-workflow/src/uaaf_workflow/context.py` |
| `uaaf/workflow/README.md` | `packages/uaaf-workflow/README.md` |

**After move:** `uaaf/workflow/`, `uaaf/observability/errors.py`, `uaaf/runtime/context.py` are **deleted** from `uaaf/`.

### 4.2 Files staying in `uaaf/` but requiring import updates

Auditing all internal `uaaf/` files that import the moved symbols (confirmed via grep 2026-05-12, 27 import lines across 16 files):

**Symbols moved to `uaaf_workflow.errors`** — `BudgetExceededError`, `DegradedError`, `FatalError`, `FrameworkError`, `RateLimitTimeout`, `RetryableError`, `classify_external_error`, `retry_policy`

| File | Old | New |
|---|---|---|
| `uaaf/providers/router.py` | `from uaaf.observability.errors import DegradedError` | `from uaaf_workflow.errors import DegradedError` |
| `uaaf/providers/fallback.py` | `from uaaf.observability.errors import DegradedError, RetryableError` | `from uaaf_workflow.errors import DegradedError, RetryableError` |
| `uaaf/providers/adapters/anthropic.py` | `from uaaf.observability.errors import classify_external_error` | `from uaaf_workflow.errors import classify_external_error` |
| `uaaf/providers/adapters/openai.py` | `from uaaf.observability.errors import (...)` | `from uaaf_workflow.errors import (...)` |
| `uaaf/observability/cost.py` | `from uaaf.observability.errors import BudgetExceededError` | `from uaaf_workflow.errors import BudgetExceededError` |
| `uaaf/observability/rate_limit.py` | `from uaaf.observability.errors import RateLimitTimeout` | `from uaaf_workflow.errors import RateLimitTimeout` |
| `uaaf/execution/sandbox.py` | `from uaaf.observability.errors import RetryableError` | `from uaaf_workflow.errors import RetryableError` |
| `uaaf/execution/agent.py` | `from uaaf.observability.errors import DegradedError, FatalError, RetryableError` | `from uaaf_workflow.errors import DegradedError, FatalError, RetryableError` |

**Symbols moved to `uaaf_workflow.context`** — `ExecutionContext`, `ContextScope`

| File | Old | New |
|---|---|---|
| `uaaf/cognitive/strategy.py` | `from uaaf.runtime.context import ExecutionContext` | `from uaaf_workflow.context import ExecutionContext` |
| `uaaf/cognitive/strategies/react.py` | _ditto_ | _ditto_ |
| `uaaf/cognitive/strategies/parallel.py` | _ditto_ | _ditto_ |
| `uaaf/cognitive/strategies/direct.py` | _ditto_ | _ditto_ |
| `uaaf/cognitive/strategies/evaluator_optimizer.py` | _ditto_ | _ditto_ |
| `uaaf/cognitive/verifier.py` | _ditto_ | _ditto_ |
| `uaaf/cognitive/verifiers/pipeline.py` | _ditto_ | _ditto_ |
| `uaaf/cognitive/verifiers/schema.py` | _ditto_ | _ditto_ |
| `uaaf/cognitive/verifiers/llm_judge.py` | _ditto_ | _ditto_ |
| `uaaf/cognitive/verifiers/ground_truth.py` | _ditto_ | _ditto_ |
| `uaaf/runtime/request_handler.py` | _ditto_ | _ditto_ |
| `uaaf/intent/selector.py` | _ditto_ | _ditto_ |
| `uaaf/execution/agent.py` | _ditto_ | _ditto_ |
| `uaaf/execution/pool.py` | `from uaaf.runtime.context import ContextScope, ExecutionContext` | `from uaaf_workflow.context import ContextScope, ExecutionContext` |
| `uaaf/execution/llm_agent.py` | `from uaaf.runtime.context import ExecutionContext` | `from uaaf_workflow.context import ExecutionContext` |

**Symbols moved to `uaaf_workflow.engine`/`state_machine`/`checkpoint`/`stores.*`**

| File | Old | New |
|---|---|---|
| `uaaf/_testing/fakes.py` | `from uaaf.workflow.engine import WorkflowResult, WorkflowStatus` | `from uaaf_workflow.engine import WorkflowResult, WorkflowStatus` |
| `uaaf/__init__.py` | `from uaaf.workflow.checkpoint import Checkpoint, ICheckpointStore` and ~5 other lines | **REMOVE entirely** (workflow symbols no longer re-exported from top-level `uaaf`) |

### 4.3 `uaaf/__init__.py` — workflow symbols removed

After Phase 8.1, `uaaf/__init__.py` no longer re-exports workflow symbols. Remove these lines:

```python
# DELETE all of these:
from uaaf.workflow.checkpoint import Checkpoint, ICheckpointStore
from uaaf.workflow.engine import IWorkflowEngine, WorkflowEngine, WorkflowResult, WorkflowStatus
from uaaf.workflow.state_machine import IState, StateMachine, StateTransition, Workflow
from uaaf.workflow.stores.file import FileCheckpointStore
from uaaf.workflow.stores.in_memory import InMemoryCheckpointStore
# Also DELETE workflow-related symbols from observability.errors re-export:
from uaaf.observability.errors import (
    BudgetExceededError, DegradedError, FatalError, FrameworkError,
    RateLimitTimeout, RetryableError, classify_external_error, retry_policy,
)
# Also DELETE runtime.context re-exports:
from uaaf.runtime.context import ContextScope, ExecutionContext
```

And the corresponding entries in `__all__`.

**Affected callsites in tests/examples/docs:** 59 files reference these paths. Each must migrate the imports. Estimated ~100-150 import lines total.

### 4.4 Sed migration map (for mechanical rewrite)

```bash
# Internal + external — same rules
s|from uaaf\.observability\.errors import|from uaaf_workflow.errors import|g
s|from uaaf\.runtime\.context import|from uaaf_workflow.context import|g
s|from uaaf\.workflow\.engine import|from uaaf_workflow.engine import|g
s|from uaaf\.workflow\.state_machine import|from uaaf_workflow.state_machine import|g
s|from uaaf\.workflow\.checkpoint import|from uaaf_workflow.checkpoint import|g
s|from uaaf\.workflow\.stores\.file import|from uaaf_workflow.stores.file import|g
s|from uaaf\.workflow\.stores\.in_memory import|from uaaf_workflow.stores.in_memory import|g
s|from uaaf\.workflow import|from uaaf_workflow import|g
```

Top-level `from uaaf import {WorkflowEngine,RetryableError,...}` must be migrated manually since the symbol list is mixed (some workflow, some still in uaaf).

## 5. Target Repo Layout (after Phase 8.1)

```
uaaf-framework/                                    (single git repo, two PyPI packages)
│
├── packages/
│   └── uaaf-workflow/                              ★ Independent library
│       ├── pyproject.toml                          (name=uaaf-workflow, version=0.2.0a1, deps=[anyio>=4.0])
│       ├── README.md                               (moved from uaaf/workflow/README.md)
│       ├── LICENSE                                  (copy of root LICENSE)
│       └── src/
│           └── uaaf_workflow/                       (top-level — underscore, separate namespace)
│               ├── __init__.py                     (re-exports for convenience: WorkflowEngine, etc.)
│               ├── py.typed                        (PEP 561 marker)
│               ├── engine.py
│               ├── state_machine.py
│               ├── checkpoint.py
│               ├── errors.py
│               ├── context.py
│               └── stores/
│                   ├── __init__.py
│                   ├── in_memory.py
│                   └── file.py
│
├── pyproject.toml                                  (uaaf — version=0.2.0a1, deps += uaaf-workflow)
├── uaaf/                                            (AI framework — NO workflow files left)
│   ├── __init__.py                                  (workflow symbols REMOVED)
│   ├── cognitive/, execution/, intent/, knowledge/, providers/, prompts/  (unchanged structure)
│   ├── observability/
│   │   ├── __init__.py                              (unchanged)
│   │   ├── cost.py, tracer.py, audit.py, rate_limit.py, _pricing.py, pricing.yaml
│   │   └── (errors.py DELETED)
│   ├── runtime/
│   │   ├── __init__.py                              (unchanged)
│   │   ├── request_handler.py                       (import updated)
│   │   └── (context.py DELETED)
│   ├── _internal/, _testing/                        (import updated in fakes.py)
│   └── (workflow/ directory DELETED entirely)
│
├── tests/, examples/, docs/                         (import updates only)
├── CHANGELOG.md
└── .github/workflows/ci.yml                          (matrix: workflow-isolation + full)
```

Build tool: **`hatchling`** (already in use).

## 6. Phase Breakdown

### Phase 8.1.A — Skeleton + Migration Plan (non-destructive)

| Task | Acceptance Criteria | Verification |
|---|---|---|
| **T01** Create `packages/uaaf-workflow/{src/uaaf_workflow/, pyproject.toml, README.md}` skeleton; copy root LICENSE | Dir tree present. `pyproject.toml` parses. | `python -c "import tomllib; tomllib.load(open('packages/uaaf-workflow/pyproject.toml','rb'))"` |
| **T02** Write `packages/MIGRATION.md` containing §4.4 sed map + §4.3 deletion list | File enumerates all migration rules | Manual review |
| **T03** Add CHANGELOG.md v0.2.0a1 UNRELEASED entry with BREAKING-change notice | Entry present at top | `head -30 CHANGELOG.md` |

**Checkpoint 8.1.A** — skeleton present, no file moves yet, `pytest -x` still green

---

### Phase 8.1.B — Build `uaaf-workflow` library (with new internal imports) ⚠️ ARCH RISK

| Task | Acceptance Criteria | Verification |
|---|---|---|
| **T04** Copy 7 workflow files + 2 ex-shared files (`errors.py`, `context.py`) → `packages/uaaf-workflow/src/uaaf_workflow/...` | Files copied. Original files in `uaaf/` still exist (deletion in T08). | `ls packages/uaaf-workflow/src/uaaf_workflow/` |
| **T05** Rewrite all imports inside the copied files to use `uaaf_workflow.*` (mechanical sed per §4.4) | `grep -rn "from uaaf\." packages/uaaf-workflow/` returns 0 lines | grep |
| **T06** Add `packages/uaaf-workflow/src/uaaf_workflow/__init__.py` with curated re-exports (`WorkflowEngine`, `IState`, `Workflow`, `StateTransition`, etc.) for ergonomic `import uaaf_workflow as wf` usage | `python -c "from uaaf_workflow import WorkflowEngine"` works after install | venv test |
| **T07** Fill `packages/uaaf-workflow/pyproject.toml`: name=uaaf-workflow, version=0.2.0a1, deps=`["anyio>=4.0"]`, hatchling build with `[tool.hatch.build.targets.wheel] packages = ["src/uaaf_workflow"]` and `[tool.hatch.build.targets.wheel.sources] "src" = ""`. Include `py.typed`. | Wheel builds. `unzip -l dist/uaaf_workflow-*.whl` shows expected files only. | `cd packages/uaaf-workflow && python -m build --wheel`, exit 0 |

**Checkpoint 8.1.B** — `uaaf-workflow` wheel exists, builds cleanly, importable in isolated venv. **STOP for human review.**

---

### Phase 8.1.C — Delete originals + update internal UAAF imports

| Task | Acceptance Criteria | Verification |
|---|---|---|
| **T08** Delete `uaaf/workflow/` (entire dir), `uaaf/observability/errors.py`, `uaaf/runtime/context.py` | Files gone | `[ ! -d uaaf/workflow ] && [ ! -f uaaf/observability/errors.py ] && [ ! -f uaaf/runtime/context.py ]` |
| **T09** Update 16 internal `uaaf/` files per §4.2 (apply sed map from §4.4) | `grep -rn "from uaaf\.workflow\|from uaaf\.observability\.errors\|from uaaf\.runtime\.context" uaaf/` returns 0 | grep |
| **T10** Strip workflow + errors + context re-exports from `uaaf/__init__.py` (per §4.3) | `uaaf/__init__.py` only re-exports AI tier symbols (`BaseAgent`, `Cost`, `Tracer`, `StructuredIntent`, etc.) | Manual review + grep |
| **T11** Update root `pyproject.toml`: bump version to `0.2.0a1`, **add** `uaaf-workflow>=0.2.0a1` to deps, **remove** `anyio>=4.0` from deps (now transitive) | Root `pyproject.toml` lists uaaf-workflow. Anyio removed from explicit deps. | `grep uaaf-workflow pyproject.toml`, `! grep "anyio" pyproject.toml` |
| **T12** Create `scripts/install-dev.sh`: `pip install -e packages/uaaf-workflow -e .[dev]` | Dev env installs both editable. `python -c "import uaaf, uaaf_workflow"` works. | bash + python test |

**Checkpoint 8.1.C** — `uaaf/` and `uaaf_workflow/` coexist; `import uaaf.cognitive` and `import uaaf_workflow.engine` both work in dev env.

---

### Phase 8.1.D — Migrate external callsites + verify

| Task | Acceptance Criteria | Verification |
|---|---|---|
| **T13** Apply sed migration map to all `.py` files in `tests/`, `examples/`, `conftest.py`, `uaaf/_testing/` | `grep -rn "from uaaf\.workflow\|from uaaf\.observability\.errors\|from uaaf\.runtime\.context" tests/ examples/ uaaf/_testing/ conftest.py` returns 0 | grep |
| **T14** Migrate top-level `from uaaf import {workflow-symbols}` in tests/examples/docs to `from uaaf_workflow.X import Y` (manual, since each line mixes workflow + AI symbols) | Tests/examples/docs use either `from uaaf import {AI-only}` or `from uaaf_workflow.X import Y` | grep verification per file |
| **T15** Apply sed map to all `.md` files in `docs/` (code snippets) | grep returns 0 in docs/ | grep |
| **T16** Fix pre-existing obs 2646 (runbook section 12 doc snippet failure) as part of T15 | `pytest tests/docs/` green | pytest exit 0 |
| **T17** Remove `__version__` references (was `uaaf.__version__`); switch any callers to `importlib.metadata.version(...)` | `grep -rn "uaaf\.__version__\|__version__ =" uaaf/ examples/ tests/` returns 0 (or only in `uaaf/__init__.py` shim if kept) | grep |
| **T18** Full local CI gate: `pytest` (604 tests), `mypy uaaf packages/uaaf-workflow/src --strict`, `ruff check`, coverage report | All green; cov ≥85% | command exit codes |

**Checkpoint 8.1.D** — 604 tests green, zero `from uaaf.workflow.*` / `from uaaf.observability.errors` / `from uaaf.runtime.context` callsites in the repo, mypy clean.

---

### Phase 8.1.E — Isolation test + CI + release prep

| Task | Acceptance Criteria | Verification |
|---|---|---|
| **T19** Write `scripts/test-workflow-isolation.sh`: fresh venv, `pip install ./packages/uaaf-workflow`, runs minimal workflow test suite, asserts `python -c "import uaaf"` fails with `ModuleNotFoundError` (proves uaaf NOT installed and NOT bundled) | Script exits 0 | Run script |
| **T20** Update `.github/workflows/ci.yml`: add `workflow-isolation` CI job running T19 script | CI has 2 jobs (full-suite + workflow-isolation); both green on PR | GH Actions UI |
| **T21** Update root `README.md` with new install section: `pip install uaaf-workflow` (workflow only) vs `pip install uaaf` (full). Link to `packages/uaaf-workflow/README.md`. | README updated | Manual review |
| **T22** Update `packages/uaaf-workflow/README.md` with standalone-library framing: what it is, install command, quickstart code | README quickstart works as copy-paste in fresh venv | Manual |
| **T23** Verify both wheels build cleanly + version pin consistency: root `pyproject.toml` declares `uaaf-workflow>=0.2.0a1` AND `packages/uaaf-workflow/pyproject.toml` is at `0.2.0a1` | Versions match | `grep "0.2.0a1" pyproject.toml packages/uaaf-workflow/pyproject.toml CHANGELOG.md` |
| **T24** Write `memory/project_phase8_1_status.md` + update `MEMORY.md` index | Memory updated | ls |

**Checkpoint 8.1 (FINAL)** — Workflow is a standalone library; clean break complete; CI proves isolation; ready for tag v0.2.0a1.

## 7. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Sed map misses an import line variant (e.g. multi-line `from X import (\n  A,\n  B,\n)`) | Medium | Medium | After bulk sed, run grep verification (T09, T13). Fix manually. |
| Hatchling fails to handle `[tool.hatch.build.targets.wheel.sources]` mapping `src` → root | Low | High | T07 explicitly verifies wheel contents via `unzip -l`. Fallback: switch to `setuptools` build backend. |
| `uaaf-workflow` wheel accidentally ships `__pycache__` or stale files | Low | Medium | T07 verifies via `unzip -l`. CI in T20 re-verifies on every build. |
| External user pip installs from a published 0.1.x wheel, expecting `from uaaf import WorkflowEngine` to work, and breaks | Medium | Medium | CHANGELOG v0.2.0a1 has BREAKING section with migration map. UAAF is still beta — acceptable. |
| Internal `uaaf/_testing/fakes.py` or `conftest.py` has imports I missed | Medium | Medium | T13 includes both. Grep verification catches drift. |
| `mypy --strict` fails because cross-package type info doesn't propagate | Medium | Medium | `py.typed` marker in `uaaf_workflow` package (T07). Test mypy in dev env. |
| Coverage drops below 85% because workflow tests no longer measure `uaaf_workflow` coverage | Medium | Low | Add `packages/uaaf-workflow/src` to coverage `source` in root `pyproject.toml` `[tool.coverage.run]`. |
| Doc snippets in `tests/docs/` still reference old import paths | High | Low | T15 + T16 cover. Pre-existing obs 2646 failure already in queue. |
| Examples in `examples/code_analysis/` break because their `main.py` uses workflow + AI imports | High | Low | T14 migrates examples. Pre-flight: `python examples/code_analysis/main.py --demo` after T14. |

## 8. Estimated Effort

| Sub-phase | Hours |
|---|---|
| 8.1.A — Skeleton | 1 |
| 8.1.B — Build workflow library | 1.5 |
| 8.1.C — Delete + internal imports | 1.5 |
| 8.1.D — External callsites + verify | 3 (mostly mechanical sed + grep verification, plus manual top-level mixed-import migration) |
| 8.1.E — Isolation test + CI + release prep | 1.5 |
| **Total** | **~8.5 hours** |

Realistic with verification: **1 working day.**

## 9. Next: Phase 8.2+

Sau khi Phase 8.1 xong và tag v0.2.0a1, các phase tiếp theo lặp lại pattern này cho từng package trong v2 architecture. Thứ tự đề xuất (giảm dần risk, theo độ phụ thuộc):

1. **Phase 8.2 — `uaaf-guardrail`**: Tách 4 file (`pipeline.py` + `filters/{pii,topic,injection}.py`). Dep chỉ `uaaf-core`. Risk thấp vì module mới, ít callsite. Đồng thời triển khai content Phase 2 của v2 §6 (rule-based only, `ContentFilter` chuyển Phase 2.5).
2. **Phase 8.3 — `uaaf-knowledge-{core,stores,rag,memory}`**: 4 wheels. Risk **cao** vì chains dependency: `core ← stores ← rag ← memory`. Cần plan riêng với 4 checkpoint.
3. **Phase 8.4 — `uaaf-execution`**: Tách `BaseAgent`, `AgentPool`, `ToolRegistry`, `SandboxManager` khỏi `uaaf/` thành package riêng. `uaaf-runtime` còn lại chỉ là facade (UAAFRuntime, RequestHandler, StreamManager).
4. **Phase 8.5 — `uaaf-eval`**: Dev-only package. Risk thấp vì offline tooling, không có production callsite.

Mỗi phase trên cần plan riêng theo template của file này (§4 audit, §6 task breakdown, §7 risk register, §8 effort estimate).
