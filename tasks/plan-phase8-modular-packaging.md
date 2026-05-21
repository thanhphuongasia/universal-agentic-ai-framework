# Phase 8 — Modular Packaging: Workflow as Independent Library

> **Architecture (chosen 2026-05-12):** `ryuu-workflow` is a **fully independent PyPI library** with its own top-level namespace `ryuu_workflow`. It is NOT a sub-package of `ryuu`. The AI framework `ryuu` depends on `ryuu-workflow` like any third-party library (e.g. anyio, pydantic).
>
> **Clean break:** No shim files in `ryuu/`. No back-compat re-exports for workflow symbols in `ryuu/__init__.py`. Consumers who used `from ryuu import WorkflowEngine` must migrate to `from ryuu_workflow.engine import WorkflowEngine`.
>
> **Scope (Phase 8.1):** Workflow extraction only. Cognitive wheel extraction is NOT in scope.

## 0. Mối quan hệ với RYUU v2 Architecture

Plan này là **bước đi đầu tiên** (proof-of-concept) của lộ trình tách package mô tả trong [`docs/architecture/ryuu-v2-architecture.md`](../docs/architecture/ryuu-v2-architecture.md). Hai doc đang **bổ sung** cho nhau, không mâu thuẫn:

| Doc | Vai trò | Scope |
|---|---|---|
| `ryuu-v2-architecture.md` §2-§4 | **Target state** — 13 packages cuối cùng | Strategic — toàn bộ refactor |
| `plan-phase8-modular-packaging.md` (file này) | **Phase 8.1** — tách 1 package (workflow) | Tactical — bước đầu, prove clean-break pattern |

**Khác biệt scope quan trọng**:
- v2 §4 đặt workflow trong namespace `ryuu.workflow.*` (sub-namespace).
- Plan 8.1 quyết định đặt workflow trong namespace `ryuu_workflow.*` (top-level riêng).
- **Lý do giữ quyết định 8.1**: Workflow muốn dùng được độc lập cho non-AI consumer (Wyckoff bot, ingestion pipeline). Namespace top-level `ryuu_workflow` rõ ràng hơn `ryuu.workflow.*`. Khi các package khác trong v2 được tách, chúng có thể chọn sub-namespace `ryuu.cognitive.*` vì luôn gắn với AI framework — không nhất quán với workflow là **chủ ý**.

**Phase 8.x roadmap** (đề xuất, sau khi 8.1 xong):
| Phase | Tách package | Tham chiếu v2 |
|---|---|---|
| **8.1** | `ryuu-workflow` (file này) | v2 §4 — adjust namespace lên `ryuu_workflow` |
| **8.2** | `ryuu-guardrail` (rule-based filters) | v2 §6 — Phase 2 content |
| **8.3** | `ryuu-knowledge-{core,stores,rag,memory}` (4 sub-packages) | v2 §4 — split god package |
| **8.4** | `ryuu-execution` tách khỏi `ryuu-runtime` | v2 §3 — runtime thành facade thuần |
| **8.5** | `ryuu-eval` | v2 §8 — dev dependency |

Mỗi Phase 8.x sẽ có plan riêng theo template của file này. Phase 8.1 xác lập **pattern** (build → delete → migrate → verify isolation), các phase sau lặp lại.

## 1. Goal

Make workflow a standalone library so consumers that need only the state-machine kernel (Wyckoff bots, ingestion pipelines, code analysis pipelines, generic DAG frameworks) can install it without touching RYUU's AI tier:

```bash
pip install ryuu-workflow         # standalone — only anyio dep
pip install ryuu                  # AI framework — auto-pulls ryuu-workflow
```

## 2. Confirmed Decisions

| # | Decision | Choice |
|---|---|---|
| 1 | Workflow lives where? | **Independent library `ryuu_workflow`** (top-level, NOT inside `ryuu/`) |
| 2 | Top-level `from ryuu import X` for workflow symbols | **Drop entirely (clean break)** |
| 3 | Version bump | **0.2.0a1** for both packages |
| 4 | `ryuu.__version__` accessor | Drop; use `importlib.metadata.version("ryuu")` or `version("ryuu-workflow")` |
| 5 | CHANGELOG | Single root CHANGELOG.md |
| 6 | Shim files in `ryuu/workflow/`, `ryuu/observability/errors.py`, `ryuu/runtime/context.py` | **NONE — files deleted entirely** |

## 3. Non-Goals

- ✋ Generalize `ExecutionContext` (remove `strategy_id` AI-specific field). Workflow-only consumers tolerate the field. Tracked as design debt.
- ✋ Separate git repo for workflow. Single monorepo, two PyPI packages.
- ✋ Move AI tier (cognitive/execution/intent/...) to a separate wheel. RYUU stays as one wheel. Cognitive split là **Phase 8.2-8.5** (xem §0, theo v2 architecture).
- ✋ Deprecation period with `DeprecationWarning`. RYUU is still beta — clean break is acceptable.
- ✋ Tách `ryuu-guardrail` / `ryuu-knowledge-*` / `ryuu-execution` / `ryuu-eval`. Tất cả là phase sau (xem §0 roadmap).
- ✋ Áp dụng full v2 namespace (`ryuu.cognitive.*` thay `ryuu_workflow.*`). Phase 8.1 cố ý dùng top-level `ryuu_workflow` cho workflow vì nó standalone-friendly. Các package khác trong Phase 8.2+ sẽ theo `ryuu.<tier>.*` per v2 §4.

## 4. Migration Audit (verified 2026-05-12)

### 4.1 Files moving FROM `ryuu/` TO `packages/ryuu-workflow/src/ryuu_workflow/`

| Old path | New path |
|---|---|
| `ryuu/workflow/__init__.py` | `packages/ryuu-workflow/src/ryuu_workflow/__init__.py` |
| `ryuu/workflow/engine.py` | `packages/ryuu-workflow/src/ryuu_workflow/engine.py` |
| `ryuu/workflow/state_machine.py` | `packages/ryuu-workflow/src/ryuu_workflow/state_machine.py` |
| `ryuu/workflow/checkpoint.py` | `packages/ryuu-workflow/src/ryuu_workflow/checkpoint.py` |
| `ryuu/workflow/stores/__init__.py` | `packages/ryuu-workflow/src/ryuu_workflow/stores/__init__.py` |
| `ryuu/workflow/stores/in_memory.py` | `packages/ryuu-workflow/src/ryuu_workflow/stores/in_memory.py` |
| `ryuu/workflow/stores/file.py` | `packages/ryuu-workflow/src/ryuu_workflow/stores/file.py` |
| `ryuu/observability/errors.py` | `packages/ryuu-workflow/src/ryuu_workflow/errors.py` |
| `ryuu/runtime/context.py` | `packages/ryuu-workflow/src/ryuu_workflow/context.py` |
| `ryuu/workflow/README.md` | `packages/ryuu-workflow/README.md` |

**After move:** `ryuu/workflow/`, `ryuu/observability/errors.py`, `ryuu/runtime/context.py` are **deleted** from `ryuu/`.

### 4.2 Files staying in `ryuu/` but requiring import updates

Auditing all internal `ryuu/` files that import the moved symbols (confirmed via grep 2026-05-12, 27 import lines across 16 files):

**Symbols moved to `ryuu_workflow.errors`** — `BudgetExceededError`, `DegradedError`, `FatalError`, `FrameworkError`, `RateLimitTimeout`, `RetryableError`, `classify_external_error`, `retry_policy`

| File | Old | New |
|---|---|---|
| `ryuu/providers/router.py` | `from ryuu.observability.errors import DegradedError` | `from ryuu_workflow.errors import DegradedError` |
| `ryuu/providers/fallback.py` | `from ryuu.observability.errors import DegradedError, RetryableError` | `from ryuu_workflow.errors import DegradedError, RetryableError` |
| `ryuu/providers/adapters/anthropic.py` | `from ryuu.observability.errors import classify_external_error` | `from ryuu_workflow.errors import classify_external_error` |
| `ryuu/providers/adapters/openai.py` | `from ryuu.observability.errors import (...)` | `from ryuu_workflow.errors import (...)` |
| `ryuu/observability/cost.py` | `from ryuu.observability.errors import BudgetExceededError` | `from ryuu_workflow.errors import BudgetExceededError` |
| `ryuu/observability/rate_limit.py` | `from ryuu.observability.errors import RateLimitTimeout` | `from ryuu_workflow.errors import RateLimitTimeout` |
| `ryuu/execution/sandbox.py` | `from ryuu.observability.errors import RetryableError` | `from ryuu_workflow.errors import RetryableError` |
| `ryuu/execution/agent.py` | `from ryuu.observability.errors import DegradedError, FatalError, RetryableError` | `from ryuu_workflow.errors import DegradedError, FatalError, RetryableError` |

**Symbols moved to `ryuu_workflow.context`** — `ExecutionContext`, `ContextScope`

| File | Old | New |
|---|---|---|
| `ryuu/cognitive/strategy.py` | `from ryuu.runtime.context import ExecutionContext` | `from ryuu_workflow.context import ExecutionContext` |
| `ryuu/cognitive/strategies/react.py` | _ditto_ | _ditto_ |
| `ryuu/cognitive/strategies/parallel.py` | _ditto_ | _ditto_ |
| `ryuu/cognitive/strategies/direct.py` | _ditto_ | _ditto_ |
| `ryuu/cognitive/strategies/evaluator_optimizer.py` | _ditto_ | _ditto_ |
| `ryuu/cognitive/verifier.py` | _ditto_ | _ditto_ |
| `ryuu/cognitive/verifiers/pipeline.py` | _ditto_ | _ditto_ |
| `ryuu/cognitive/verifiers/schema.py` | _ditto_ | _ditto_ |
| `ryuu/cognitive/verifiers/llm_judge.py` | _ditto_ | _ditto_ |
| `ryuu/cognitive/verifiers/ground_truth.py` | _ditto_ | _ditto_ |
| `ryuu/runtime/request_handler.py` | _ditto_ | _ditto_ |
| `ryuu/intent/selector.py` | _ditto_ | _ditto_ |
| `ryuu/execution/agent.py` | _ditto_ | _ditto_ |
| `ryuu/execution/pool.py` | `from ryuu.runtime.context import ContextScope, ExecutionContext` | `from ryuu_workflow.context import ContextScope, ExecutionContext` |
| `ryuu/execution/llm_agent.py` | `from ryuu.runtime.context import ExecutionContext` | `from ryuu_workflow.context import ExecutionContext` |

**Symbols moved to `ryuu_workflow.engine`/`state_machine`/`checkpoint`/`stores.*`**

| File | Old | New |
|---|---|---|
| `ryuu/_testing/fakes.py` | `from ryuu.workflow.engine import WorkflowResult, WorkflowStatus` | `from ryuu_workflow.engine import WorkflowResult, WorkflowStatus` |
| `ryuu/__init__.py` | `from ryuu.workflow.checkpoint import Checkpoint, ICheckpointStore` and ~5 other lines | **REMOVE entirely** (workflow symbols no longer re-exported from top-level `ryuu`) |

### 4.3 `ryuu/__init__.py` — workflow symbols removed

After Phase 8.1, `ryuu/__init__.py` no longer re-exports workflow symbols. Remove these lines:

```python
# DELETE all of these:
from ryuu.workflow.checkpoint import Checkpoint, ICheckpointStore
from ryuu.workflow.engine import IWorkflowEngine, WorkflowEngine, WorkflowResult, WorkflowStatus
from ryuu.workflow.state_machine import IState, StateMachine, StateTransition, Workflow
from ryuu.workflow.stores.file import FileCheckpointStore
from ryuu.workflow.stores.in_memory import InMemoryCheckpointStore
# Also DELETE workflow-related symbols from observability.errors re-export:
from ryuu.observability.errors import (
    BudgetExceededError, DegradedError, FatalError, FrameworkError,
    RateLimitTimeout, RetryableError, classify_external_error, retry_policy,
)
# Also DELETE runtime.context re-exports:
from ryuu.runtime.context import ContextScope, ExecutionContext
```

And the corresponding entries in `__all__`.

**Affected callsites in tests/examples/docs:** 59 files reference these paths. Each must migrate the imports. Estimated ~100-150 import lines total.

### 4.4 Sed migration map (for mechanical rewrite)

```bash
# Internal + external — same rules
s|from ryuu\.observability\.errors import|from ryuu_workflow.errors import|g
s|from ryuu\.runtime\.context import|from ryuu_workflow.context import|g
s|from ryuu\.workflow\.engine import|from ryuu_workflow.engine import|g
s|from ryuu\.workflow\.state_machine import|from ryuu_workflow.state_machine import|g
s|from ryuu\.workflow\.checkpoint import|from ryuu_workflow.checkpoint import|g
s|from ryuu\.workflow\.stores\.file import|from ryuu_workflow.stores.file import|g
s|from ryuu\.workflow\.stores\.in_memory import|from ryuu_workflow.stores.in_memory import|g
s|from ryuu\.workflow import|from ryuu_workflow import|g
```

Top-level `from ryuu import {WorkflowEngine,RetryableError,...}` must be migrated manually since the symbol list is mixed (some workflow, some still in ryuu).

## 5. Target Repo Layout (after Phase 8.1)

```
ryuu-framework/                                    (single git repo, two PyPI packages)
│
├── packages/
│   └── ryuu-workflow/                              ★ Independent library
│       ├── pyproject.toml                          (name=ryuu-workflow, version=0.2.0a1, deps=[anyio>=4.0])
│       ├── README.md                               (moved from ryuu/workflow/README.md)
│       ├── LICENSE                                  (copy of root LICENSE)
│       └── src/
│           └── ryuu_workflow/                       (top-level — underscore, separate namespace)
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
├── pyproject.toml                                  (ryuu — version=0.2.0a1, deps += ryuu-workflow)
├── ryuu/                                            (AI framework — NO workflow files left)
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
| **T01** Create `packages/ryuu-workflow/{src/ryuu_workflow/, pyproject.toml, README.md}` skeleton; copy root LICENSE | Dir tree present. `pyproject.toml` parses. | `python -c "import tomllib; tomllib.load(open('packages/ryuu-workflow/pyproject.toml','rb'))"` |
| **T02** Write `packages/MIGRATION.md` containing §4.4 sed map + §4.3 deletion list | File enumerates all migration rules | Manual review |
| **T03** Add CHANGELOG.md v0.2.0a1 UNRELEASED entry with BREAKING-change notice | Entry present at top | `head -30 CHANGELOG.md` |

**Checkpoint 8.1.A** — skeleton present, no file moves yet, `pytest -x` still green

---

### Phase 8.1.B — Build `ryuu-workflow` library (with new internal imports) ⚠️ ARCH RISK

| Task | Acceptance Criteria | Verification |
|---|---|---|
| **T04** Copy 7 workflow files + 2 ex-shared files (`errors.py`, `context.py`) → `packages/ryuu-workflow/src/ryuu_workflow/...` | Files copied. Original files in `ryuu/` still exist (deletion in T08). | `ls packages/ryuu-workflow/src/ryuu_workflow/` |
| **T05** Rewrite all imports inside the copied files to use `ryuu_workflow.*` (mechanical sed per §4.4) | `grep -rn "from ryuu\." packages/ryuu-workflow/` returns 0 lines | grep |
| **T06** Add `packages/ryuu-workflow/src/ryuu_workflow/__init__.py` with curated re-exports (`WorkflowEngine`, `IState`, `Workflow`, `StateTransition`, etc.) for ergonomic `import ryuu_workflow as wf` usage | `python -c "from ryuu_workflow import WorkflowEngine"` works after install | venv test |
| **T07** Fill `packages/ryuu-workflow/pyproject.toml`: name=ryuu-workflow, version=0.2.0a1, deps=`["anyio>=4.0"]`, hatchling build with `[tool.hatch.build.targets.wheel] packages = ["src/ryuu_workflow"]` and `[tool.hatch.build.targets.wheel.sources] "src" = ""`. Include `py.typed`. | Wheel builds. `unzip -l dist/ryuu_workflow-*.whl` shows expected files only. | `cd packages/ryuu-workflow && python -m build --wheel`, exit 0 |

**Checkpoint 8.1.B** — `ryuu-workflow` wheel exists, builds cleanly, importable in isolated venv. **STOP for human review.**

---

### Phase 8.1.C — Delete originals + update internal RYUU imports

| Task | Acceptance Criteria | Verification |
|---|---|---|
| **T08** Delete `ryuu/workflow/` (entire dir), `ryuu/observability/errors.py`, `ryuu/runtime/context.py` | Files gone | `[ ! -d ryuu/workflow ] && [ ! -f ryuu/observability/errors.py ] && [ ! -f ryuu/runtime/context.py ]` |
| **T09** Update 16 internal `ryuu/` files per §4.2 (apply sed map from §4.4) | `grep -rn "from ryuu\.workflow\|from ryuu\.observability\.errors\|from ryuu\.runtime\.context" ryuu/` returns 0 | grep |
| **T10** Strip workflow + errors + context re-exports from `ryuu/__init__.py` (per §4.3) | `ryuu/__init__.py` only re-exports AI tier symbols (`BaseAgent`, `Cost`, `Tracer`, `StructuredIntent`, etc.) | Manual review + grep |
| **T11** Update root `pyproject.toml`: bump version to `0.2.0a1`, **add** `ryuu-workflow>=0.2.0a1` to deps, **remove** `anyio>=4.0` from deps (now transitive) | Root `pyproject.toml` lists ryuu-workflow. Anyio removed from explicit deps. | `grep ryuu-workflow pyproject.toml`, `! grep "anyio" pyproject.toml` |
| **T12** Create `scripts/install-dev.sh`: `pip install -e packages/ryuu-workflow -e .[dev]` | Dev env installs both editable. `python -c "import ryuu, ryuu_workflow"` works. | bash + python test |

**Checkpoint 8.1.C** — `ryuu/` and `ryuu_workflow/` coexist; `import ryuu.cognitive` and `import ryuu_workflow.engine` both work in dev env.

---

### Phase 8.1.D — Migrate external callsites + verify

| Task | Acceptance Criteria | Verification |
|---|---|---|
| **T13** Apply sed migration map to all `.py` files in `tests/`, `examples/`, `conftest.py`, `ryuu/_testing/` | `grep -rn "from ryuu\.workflow\|from ryuu\.observability\.errors\|from ryuu\.runtime\.context" tests/ examples/ ryuu/_testing/ conftest.py` returns 0 | grep |
| **T14** Migrate top-level `from ryuu import {workflow-symbols}` in tests/examples/docs to `from ryuu_workflow.X import Y` (manual, since each line mixes workflow + AI symbols) | Tests/examples/docs use either `from ryuu import {AI-only}` or `from ryuu_workflow.X import Y` | grep verification per file |
| **T15** Apply sed map to all `.md` files in `docs/` (code snippets) | grep returns 0 in docs/ | grep |
| **T16** Fix pre-existing obs 2646 (runbook section 12 doc snippet failure) as part of T15 | `pytest tests/docs/` green | pytest exit 0 |
| **T17** Remove `__version__` references (was `ryuu.__version__`); switch any callers to `importlib.metadata.version(...)` | `grep -rn "ryuu\.__version__\|__version__ =" ryuu/ examples/ tests/` returns 0 (or only in `ryuu/__init__.py` shim if kept) | grep |
| **T18** Full local CI gate: `pytest` (604 tests), `mypy ryuu packages/ryuu-workflow/src --strict`, `ruff check`, coverage report | All green; cov ≥85% | command exit codes |

**Checkpoint 8.1.D** — 604 tests green, zero `from ryuu.workflow.*` / `from ryuu.observability.errors` / `from ryuu.runtime.context` callsites in the repo, mypy clean.

---

### Phase 8.1.E — Isolation test + CI + release prep

| Task | Acceptance Criteria | Verification |
|---|---|---|
| **T19** Write `scripts/test-workflow-isolation.sh`: fresh venv, `pip install ./packages/ryuu-workflow`, runs minimal workflow test suite, asserts `python -c "import ryuu"` fails with `ModuleNotFoundError` (proves ryuu NOT installed and NOT bundled) | Script exits 0 | Run script |
| **T20** Update `.github/workflows/ci.yml`: add `workflow-isolation` CI job running T19 script | CI has 2 jobs (full-suite + workflow-isolation); both green on PR | GH Actions UI |
| **T21** Update root `README.md` with new install section: `pip install ryuu-workflow` (workflow only) vs `pip install ryuu` (full). Link to `packages/ryuu-workflow/README.md`. | README updated | Manual review |
| **T22** Update `packages/ryuu-workflow/README.md` with standalone-library framing: what it is, install command, quickstart code | README quickstart works as copy-paste in fresh venv | Manual |
| **T23** Verify both wheels build cleanly + version pin consistency: root `pyproject.toml` declares `ryuu-workflow>=0.2.0a1` AND `packages/ryuu-workflow/pyproject.toml` is at `0.2.0a1` | Versions match | `grep "0.2.0a1" pyproject.toml packages/ryuu-workflow/pyproject.toml CHANGELOG.md` |
| **T24** Write `memory/project_phase8_1_status.md` + update `MEMORY.md` index | Memory updated | ls |

**Checkpoint 8.1 (FINAL)** — Workflow is a standalone library; clean break complete; CI proves isolation; ready for tag v0.2.0a1.

## 7. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Sed map misses an import line variant (e.g. multi-line `from X import (\n  A,\n  B,\n)`) | Medium | Medium | After bulk sed, run grep verification (T09, T13). Fix manually. |
| Hatchling fails to handle `[tool.hatch.build.targets.wheel.sources]` mapping `src` → root | Low | High | T07 explicitly verifies wheel contents via `unzip -l`. Fallback: switch to `setuptools` build backend. |
| `ryuu-workflow` wheel accidentally ships `__pycache__` or stale files | Low | Medium | T07 verifies via `unzip -l`. CI in T20 re-verifies on every build. |
| External user pip installs from a published 0.1.x wheel, expecting `from ryuu import WorkflowEngine` to work, and breaks | Medium | Medium | CHANGELOG v0.2.0a1 has BREAKING section with migration map. RYUU is still beta — acceptable. |
| Internal `ryuu/_testing/fakes.py` or `conftest.py` has imports I missed | Medium | Medium | T13 includes both. Grep verification catches drift. |
| `mypy --strict` fails because cross-package type info doesn't propagate | Medium | Medium | `py.typed` marker in `ryuu_workflow` package (T07). Test mypy in dev env. |
| Coverage drops below 85% because workflow tests no longer measure `ryuu_workflow` coverage | Medium | Low | Add `packages/ryuu-workflow/src` to coverage `source` in root `pyproject.toml` `[tool.coverage.run]`. |
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

1. **Phase 8.2 — `ryuu-guardrail`**: Tách 4 file (`pipeline.py` + `filters/{pii,topic,injection}.py`). Dep chỉ `ryuu-core`. Risk thấp vì module mới, ít callsite. Đồng thời triển khai content Phase 2 của v2 §6 (rule-based only, `ContentFilter` chuyển Phase 2.5).
2. **Phase 8.3 — `ryuu-knowledge-{core,stores,rag,memory}`**: 4 wheels. Risk **cao** vì chains dependency: `core ← stores ← rag ← memory`. Cần plan riêng với 4 checkpoint.
3. **Phase 8.4 — `ryuu-execution`**: Tách `BaseAgent`, `AgentPool`, `ToolRegistry`, `SandboxManager` khỏi `ryuu/` thành package riêng. `ryuu-runtime` còn lại chỉ là facade (RYUURuntime, RequestHandler, StreamManager).
4. **Phase 8.5 — `ryuu-eval`**: Dev-only package. Risk thấp vì offline tooling, không có production callsite.

Mỗi phase trên cần plan riêng theo template của file này (§4 audit, §6 task breakdown, §7 risk register, §8 effort estimate).
