# Phase 8.2 — uaaf-core: Zero-Dep Foundation Package

> **Date**: 2026-05-20  
> **Depends on**: Phase 8.1 complete (commit 7f72a95)  
> **See**: `docs/architecture/uaaf-v2-architecture.md` §2–§4 for target architecture

## 0. Mối quan hệ với Phase 8.1 và v2 Architecture

Phase 8.1 đặt `errors.py` + `context.py` vào `uaaf_workflow` như một bước tạm thời.  
Phase 8.2 di chuyển chúng về đúng chỗ: `uaaf_core`.

**Key insight — zero callsite migration**:  
`uaaf_workflow` sẽ giữ `errors.py` và `context.py` nhưng đổi thành **thin re-export** từ `uaaf_core`.  
Mọi callsite hiện tại (`from uaaf_workflow.errors import X`) tiếp tục hoạt động không đổi.  
Chỉ **new code** viết đúng từ `uaaf_core.*`.

## 1. Goal

Tạo `uaaf-core` — package zero dependency (chỉ stdlib) chứa:

```bash
pip install uaaf-core           # zero dep — chỉ stdlib
pip install uaaf-workflow       # depends on uaaf-core
pip install uaaf                # depends on uaaf-core + uaaf-workflow + providers
```

**Lợi ích chính**:
- Test agent đơn giản không cần mock: `BaseAgent(agent_id="test")` với NullObject defaults.
- Protocol definitions ở 1 chỗ — mọi package implement Protocol từ uaaf-core.
- Consumer-only install: domain logic không kéo opentelemetry/openai.

## 2. Nội dung uaaf-core

```
packages/uaaf-core/src/uaaf_core/
├── __init__.py          re-export tất cả public symbols
├── errors.py            MOVE từ uaaf_workflow.errors (errors.py giữ nguyên)
├── context.py           MOVE từ uaaf_workflow.context (context.py giữ nguyên)
├── models.py            EXTRACT từ uaaf/intent/models.py + uaaf/execution/agent.py (Task, AgentResult, Cost)
├── protocols.py         NEW — ICostTracker, ITracer, IAuditLogger, IRateLimiter Protocol interfaces
└── nulls.py             NEW — NullCostTracker, NullTracer, NullAuditLogger, NullRateLimiter
```

### 2.1 errors.py — Move (không đổi nội dung)

`FrameworkError`, `RetryableError`, `DegradedError`, `FatalError`,
`BudgetExceededError`, `RateLimitTimeout`, `RetryDecision`, `retry_policy`, `classify_external_error`

**Sau khi move**: `uaaf_workflow/errors.py` trở thành re-export:
```python
# uaaf_workflow/errors.py — backward-compat re-export
from uaaf_core.errors import *  # noqa: F401, F403
```

### 2.2 context.py — Move (không đổi nội dung)

`ContextScope`, `ExecutionContext`

**Sau khi move**: `uaaf_workflow/context.py` trở thành re-export:
```python
# uaaf_workflow/context.py — backward-compat re-export
from uaaf_core.context import *  # noqa: F401, F403
```

### 2.3 models.py — Extract

| Symbol | Từ | Dep |
|---|---|---|
| `Cost` | `uaaf/observability/cost.py` | pure dataclass — stdlib only |
| `Task` | `uaaf/execution/agent.py` | depends on `Cost` |
| `AgentResult` | `uaaf/execution/agent.py` | depends on `Cost` |
| `StructuredIntent` | `uaaf/intent/models.py` | depends on `ComplexityLevel`, `ModelTier` |
| `CognitiveResult` | `uaaf/intent/models.py` | stdlib only |
| `CostEstimate` | `uaaf/intent/models.py` | stdlib only |
| `ComplexityLevel` | `uaaf/intent/models.py` | stdlib only |
| `ModelTier` | `uaaf/intent/models.py` | stdlib only |

**Sau khi extract**: Các file gốc re-import từ `uaaf_core.models`.  
~75 callsite hiện tại không cần đổi (gốc re-export về đúng path).

### 2.4 protocols.py — NEW

```python
@runtime_checkable
class ICostTracker(Protocol):
    def record(self, scope: str, cost: "Cost") -> None: ...
    def enforce(self, scope: str, estimated: float) -> None: ...
    def summary(self, scope: str) -> "Cost": ...

@runtime_checkable
class ITracer(Protocol):
    def span(self, name: str, *args: Any, **kwargs: Any) -> AbstractContextManager[None]: ...

@runtime_checkable
class IAuditLogger(Protocol):
    def log_start(self, task: Any, ctx: Any) -> None: ...
    def log_complete(self, task: Any, result: Any) -> None: ...
    def log_error(self, task: Any, exc: Exception) -> None: ...

@runtime_checkable
class IRateLimiter(Protocol):
    async def acquire(self, scope: str, agent_id: str) -> None: ...
```

### 2.5 nulls.py — NEW

```python
class NullCostTracker:
    def record(self, scope, cost): pass
    def enforce(self, scope, estimated): pass
    def summary(self, scope): return Cost.zero()

class NullTracer:
    @contextmanager
    def span(self, *args, **kwargs): yield

class NullAuditLogger:
    def log_start(self, *args): pass
    def log_complete(self, *args): pass
    def log_error(self, *args): pass

class NullRateLimiter:
    async def acquire(self, *args): pass
```

**Lợi ích ngay lập tức**: `BaseAgent` dùng NullObject defaults thay vì require 4 dep:
```python
@dataclass
class BaseAgent(ABC):
    agent_id: str
    cost_tracker: ICostTracker = field(default_factory=NullCostTracker)
    tracer: ITracer             = field(default_factory=NullTracer)
    audit_logger: IAuditLogger  = field(default_factory=NullAuditLogger)
    rate_limiter: IRateLimiter  = field(default_factory=NullRateLimiter)
```

## 3. Decisions

| # | Quyết định | Chọn |
|---|---|---|
| D1 | Namespace: `uaaf_core` hay `uaaf.core`? | `uaaf_core` — giống pattern `uaaf_workflow`, standalone-friendly |
| D2 | `uaaf_workflow.errors/context` sau khi move? | Thin re-export (backward-compat), warn sau v0.3 |
| D3 | `uaaf/intent/models.py` và `uaaf/execution/agent.py` sau extract? | Re-import từ `uaaf_core.models`, giữ nguyên public path |
| D4 | `Cost` move vào `uaaf_core` hay giữ ở observability? | Move vào `uaaf_core.models` — Cost là model, không phải observability logic |
| D5 | `uaaf-workflow` dep thêm `uaaf-core`? | Có — `uaaf_workflow` import errors/context từ `uaaf_core` |

## 4. Migration Audit

### 4.1 Files moving FROM `uaaf_workflow` TO `uaaf_core`

| Old path | New path |
|---|---|
| `packages/uaaf-workflow/src/uaaf_workflow/errors.py` | `packages/uaaf-core/src/uaaf_core/errors.py` |
| `packages/uaaf-workflow/src/uaaf_workflow/context.py` | `packages/uaaf-core/src/uaaf_core/context.py` |

**uaaf_workflow/errors.py** sau đó = 2 dòng re-export. Tất cả `from uaaf_workflow.errors import X` tiếp tục hoạt động.

### 4.2 Files extracted FROM `uaaf/` — re-import tại gốc

| Source | Symbols extract sang uaaf_core.models |
|---|---|
| `uaaf/observability/cost.py` | `Cost` |
| `uaaf/execution/agent.py` | `Task`, `AgentResult` |
| `uaaf/intent/models.py` | `StructuredIntent`, `CognitiveResult`, `CostEstimate`, `ComplexityLevel`, `ModelTier` |

Sau extract: các file gốc giữ `from uaaf_core.models import X` → public import path `from uaaf.intent.models import X` tiếp tục hoạt động.

### 4.3 uaaf-workflow/pyproject.toml — thêm dep

```toml
dependencies = [
    "anyio>=4.0",
    "uaaf-core>=0.2.0a1",    # ← ADD
]
```

### 4.4 Root pyproject.toml — thêm dep

```toml
dependencies = [
    "uaaf-workflow>=0.2.0a1",
    "uaaf-core>=0.2.0a1",    # ← ADD (explicit, dù uaaf-workflow đã pull transitive)
    ...
]
```

### 4.5 BaseAgent — wiring NullObjects

`uaaf/execution/agent.py`: thay 4 dep bắt buộc bằng NullObject defaults.  
Existing tests không cần mock nữa — đây là kết quả TDD phải prove.

## 5. TDD Strategy

> **Nguyên tắc**: Viết tests cho `uaaf-core` TRƯỚC khi copy/create code.

### RED phase (trước implement):

```
tests/unit/core/test_errors.py       — errors heirarchy, retry_policy, classify_external_error
tests/unit/core/test_context.py      — ExecutionContext frozen, ContextScope defaults
tests/unit/core/test_models.py       — Cost.zero(), Task, AgentResult, StructuredIntent
tests/unit/core/test_protocols.py    — isinstance checks với NullObjects (Protocol compliance)
tests/unit/core/test_nulls.py        — NullCostTracker no-op, NullTracer context manager, NullRateLimiter await-safe
```

### GREEN phase (sau implement):

Tests pass. Sau đó chạy toàn bộ suite (604) để prove backward-compat re-exports không break gì.

## 6. Phase Breakdown

### Phase 8.2.A — Skeleton + tests (RED)

| Task | Acceptance Criteria | Verification |
|---|---|---|
| **T01** Create `packages/uaaf-core/{src/uaaf_core/, pyproject.toml, README.md, LICENSE}` skeleton | `python -c "import tomllib; tomllib.load(...)"` | tomllib parse |
| **T02** Write `tests/unit/core/test_errors.py` (RED — import từ uaaf_core.errors) | pytest collect → ImportError (package chưa có) | `pytest tests/unit/core/test_errors.py` fails with ImportError |
| **T03** Write `tests/unit/core/test_context.py` (RED) | ditto | ImportError |
| **T04** Write `tests/unit/core/test_models.py` (RED) | ditto | ImportError |
| **T05** Write `tests/unit/core/test_protocols.py` + `test_nulls.py` (RED) | ditto | ImportError |

**Checkpoint 8.2.A** — Skeleton present, 5 test files RED (ImportError expected).

---

### Phase 8.2.B — Implement uaaf-core (GREEN)

| Task | Acceptance Criteria | Verification |
|---|---|---|
| **T06** Copy `errors.py` + `context.py` từ `uaaf_workflow` vào `uaaf_core`, sửa internal imports | `from uaaf_core.errors import RetryableError` works | pytest T02 GREEN |
| **T07** Write `uaaf_core/models.py` — extract Cost, Task, AgentResult, StructuredIntent, CognitiveResult, CostEstimate, ComplexityLevel, ModelTier | All symbols importable | pytest T04 GREEN |
| **T08** Write `uaaf_core/protocols.py` — ICostTracker, ITracer, IAuditLogger, IRateLimiter | Protocol definitions importable | pytest T05 (protocol part) GREEN |
| **T09** Write `uaaf_core/nulls.py` — NullCostTracker, NullTracer, NullAuditLogger, NullRateLimiter | `isinstance(NullCostTracker(), ICostTracker)` = True | pytest T05 (nulls part) GREEN |
| **T10** Write `uaaf_core/__init__.py` — curated re-exports | `from uaaf_core import RetryableError, ExecutionContext, NullCostTracker` | smoke import |

**Checkpoint 8.2.B** — All 5 new test files GREEN, package importable.

---

### Phase 8.2.C — Wire uaaf-workflow → uaaf-core

| Task | Acceptance Criteria | Verification |
|---|---|---|
| **T11** Fill `packages/uaaf-core/pyproject.toml`: `name=uaaf-core, version=0.2.0a1, deps=[]`, build wheel | Wheel builds, `unzip -l` shows correct files | `python -m build --wheel` + unzip |
| **T12** Update `packages/uaaf-workflow/pyproject.toml`: add `uaaf-core>=0.2.0a1` dep | Dep listed | grep |
| **T13** Replace `uaaf_workflow/errors.py` content với thin re-export từ `uaaf_core.errors` | `from uaaf_workflow.errors import RetryableError` still works | import test |
| **T14** Replace `uaaf_workflow/context.py` content với thin re-export từ `uaaf_core.context` | `from uaaf_workflow.context import ExecutionContext` still works | import test |

**Checkpoint 8.2.C** — uaaf-workflow depends on uaaf-core, backward-compat re-exports work.

---

### Phase 8.2.D — Wire uaaf → uaaf-core + NullObject BaseAgent

| Task | Acceptance Criteria | Verification |
|---|---|---|
| **T15** `uaaf/observability/cost.py`: remove `Cost` class definition, replace with `from uaaf_core.models import Cost` | `from uaaf.observability.cost import Cost` still works | import test |
| **T16** `uaaf/intent/models.py`: remove model definitions, replace with re-import từ `uaaf_core.models` | `from uaaf.intent.models import StructuredIntent` still works | import test |
| **T17** `uaaf/execution/agent.py`: remove Task + AgentResult definitions, re-import từ `uaaf_core.models`. Wire NullObject defaults vào `BaseAgent` fields. | `BaseAgent(agent_id="x")` constructs without args. `isinstance(BaseAgent.cost_tracker, ICostTracker)` = True | test |
| **T18** Root `pyproject.toml`: add `uaaf-core>=0.2.0a1` dep | grep | dep listed |
| **T19** Full CI gate: 604 tests green, uaaf-core tests green | All pass | pytest |

**Checkpoint 8.2.D** — Full suite green, NullObject BaseAgent works, backward-compat proven.

---

### Phase 8.2.E — Isolation test + scripts

| Task | Acceptance Criteria | Verification |
|---|---|---|
| **T20** Write `scripts/test-core-isolation.sh`: fresh venv + `pip install uaaf-core`, assert `import uaaf` fails | Script exits 0 | run script |
| **T21** Update `.github/workflows/ci.yml`: add `core-isolation` job | CI has 3 jobs | review |
| **T22** Update `packages/MIGRATION.md`: add Phase 8.2 section với note về uaaf_core.* as canonical path | File updated | review |
| **T23** Update CHANGELOG.md v0.2.0a1 section với Phase 8.2 changes | Entry present | head CHANGELOG |
| **T24** Update memory + todo | Files updated | ls |

**Checkpoint 8.2 FINAL** — uaaf-core standalone, uaaf-workflow backward-compat, 604+ tests green.

## 7. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `Cost` có circular import vì `Task` depends on `Cost` và cả 2 move vào `models.py` | Low | Medium | Đặt `Cost` trước `Task` trong cùng file, tránh relative import cycles |
| `StructuredIntent.suggested_strategy` dùng `DIRECT` string constant — cần import thêm | Medium | Low | Extract constant vào `uaaf_core.models` cùng lúc |
| `NullTracer.span()` dùng `contextmanager` — test async context cần care | Low | Low | Test explicitly với `async with` + `await` |
| `uaaf_workflow` re-export bằng `import *` — mypy strict có thể complain | Medium | Low | Dùng explicit re-export thay `*`: `from uaaf_core.errors import RetryableError as RetryableError` |
| `BaseAgent` NullObject fields — existing tests mock `cost_tracker` explicitly | Low | Low | NullObject mặc định không break mock — tests có inject mock vẫn hoạt động |

## 8. Estimated Effort

| Sub-phase | Hours |
|---|---|
| 8.2.A — Skeleton + RED tests | 1 |
| 8.2.B — Implement uaaf-core (GREEN) | 1.5 |
| 8.2.C — Wire uaaf-workflow → uaaf-core | 0.5 |
| 8.2.D — Wire uaaf → uaaf-core + NullObject BaseAgent | 2 |
| 8.2.E — Isolation + CI + docs | 1 |
| **Total** | **~6 hours** |
