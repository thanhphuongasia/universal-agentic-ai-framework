# Implementation Plan: Phase 7 — Workflow Engine + State Machine + Checkpoint

> **Spec**: `docs/ryuu-framework-spec.md` §4 (project structure), §7.4 (batch workflow sequence), §11 (failure modes).
> **CI gate đầu vào (Phase 6)**: 487 pass + 1 skipped, ruff ✓, mypy ✓, coverage 87.77%.
> **Pattern reference**: `ryuu/knowledge/` — Protocol-at-top-level + impl-in-subdir.

---

## Overview

`ryuu/workflow/` đang trống. Spec §7.4 yêu cầu **batch mode** — 1 workflow = chuỗi states, mỗi state dispatch agent qua `AgentPool`, kết quả lưu checkpoint, **SIGKILL-safe resume** từ checkpoint mới nhất. 4/5 product cần feature này:

- **Code Analysis**: ingestion (PARSING → PHASE1_ENHANCEMENT → PHASE2_GOLD_DERIVATION).
- **Flashcard**: scheduled batch cho spaced repetition.
- **Stock trading**: signal generation pipeline.
- **AI coding practice**: gen problem → run code → grade.

Phase 7 build **3 module + 2 store impl** theo pattern knowledge/:

```
ryuu/workflow/
├── __init__.py
├── engine.py            # IWorkflowEngine Protocol + WorkflowEngine + WorkflowResult + WorkflowStatus
├── state_machine.py     # IState Protocol + StateMachine + Workflow + StateTransition
├── checkpoint.py        # ICheckpointStore Protocol + Checkpoint
└── stores/
    ├── __init__.py
    ├── in_memory.py     # InMemoryCheckpointStore (tests, dev)
    └── file.py          # FileCheckpointStore (JSON-backed, SIGKILL-safe)
```

**Scope KHÔNG bao gồm**:
- Workflow visual editor (spec §13 out-of-scope).
- Distributed/multi-process orchestration (single-process only trong v0.1).
- Postgres/Redis checkpoint stores (sau khi v1.0 stable).
- Concrete workflow definitions cho từng product (đó là job product layer).

---

## Architecture Decisions

### AD-1. `IWorkflowEngine` là Protocol — `WorkflowEngine` là default impl
Mirror `IKnowledgeBackbone` + `MemoryBackbone` pattern. Lý do giữ Protocol:
- Sau này có thể có `DurableWorkflowEngine` (Temporal-like) hoặc `DistributedWorkflowEngine`.
- Contract test bắt được spec drift trước khi product team adopt nhầm.
Trade-off: thêm 1 lớp gián tiếp khi debug — chấp nhận được vì Protocol structural typing không tăng runtime cost.

### AD-2. `ICheckpointStore` impls trong `stores/` subdir
Mirror `knowledge/memory/` + `knowledge/graph/` layout. Mở rộng dễ:
- `stores/in_memory.py` — default cho test + dev.
- `stores/file.py` — JSON-on-disk cho SIGKILL recovery.
- Phase 8+: `stores/sqlite.py`, `stores/postgres.py`, `stores/redis.py` — không phá API.

### AD-3. Engine sequential, không task-group
Spec §7.4 sequence: PARSING → PHASE1 → PHASE2 — tuần tự. Engine **không** dùng `anyio.create_task_group()` ở engine level. Nếu state cần fan-out, đó là `IState.execute()` impl quyết định (có thể gọi `AgentPool.fan_out` bên trong). Engine giữ contract đơn giản: 1 state tại 1 thời điểm.

### AD-4. `IState.execute()` trả về `StateTransition`, không phải `next_state: str`
```python
@dataclass
class StateTransition:
    next_state: str | None    # None = terminal
    output: Any
    metadata: dict[str, Any] = field(default_factory=dict)
```
Lý do: state cần truyền output đến state kế (`PARSING.output → PHASE1.input`). Trả về tuple `(next, output)` qua dataclass có name rõ hơn.

### AD-5. Retry logic dùng lại `ryuu.observability.errors.retry_policy()`
Spec §7.4 có `opt RetryableError → Engine→Engine: exponential backoff`. Không tự viết retry — gọi `retry_policy(exc, attempt)` đã có sẵn (exponential backoff + jitter). Mỗi state có `max_state_retries=3` (config-able trên Engine).

### AD-6. Tiered error handling
- `RetryableError`: Engine retry với backoff (`max_state_retries` lần).
- `DegradedError`: Engine log warning + tiếp tục state hiện tại (caller xử lý fallback nếu cần).
- `FatalError`: Engine dừng, ghi checkpoint với `status=FAILED`, return `WorkflowResult(status=FAILED, error=...)`. KHÔNG raise — caller check `.status`.

### AD-7. Checkpoint serialization: `output: Any` constraint document hoá
- `InMemoryCheckpointStore`: lưu raw object — không constraint.
- `FileCheckpointStore`: `json.dumps(checkpoint.output)` — output **phải** JSON-serializable. Document rõ trong docstring; raise `FatalError` nếu không serialize được khi save.
- Trade-off: product team cần đảm bảo output JSON-serializable nếu dùng FileCheckpointStore (string, int, dict, list — không pickle, không object instance phức tạp).

### AD-8. Workflow là dataclass, không phải class với behavior
```python
@dataclass(frozen=True)
class Workflow:
    workflow_id: str
    states: dict[str, IState]
    initial_state: str
    terminal_states: set[str]
```
Workflow = **definition** (data). State machine + Engine = **behavior**. Tránh god-class.

### AD-9. KHÔNG implement Workflow Builder / DSL trong v0.1
Product team dựng `Workflow` trực tiếp bằng dataclass + dict. Builder/DSL là tooling, defer Phase 8+.

### AD-10. `RequestHandler` là single entry point của cognitive tier — không cho phép gọi `agent.execute()` trực tiếp từ product code

**Gap hiện tại**: `ICognitiveStrategy`, `StrategySelector`, `AgentPool` đã tồn tại nhưng **không ai wire chúng lại**. Các example hiện tại (`todo_app`, `stock_advisory`) gọi `agent.execute(task, ctx)` trực tiếp → bỏ qua hoàn toàn `IntentAnalyzer`, `StrategySelector`, `ICognitiveStrategy`. `AgentPool` chỉ được dùng trong tests.

**Decision**: Thêm `ryuu/runtime/request_handler.py` — `RequestHandler` dataclass là **single entry point** cho conversational mode. Product code gọi:
```python
result = await handler.handle(message="...", context=ctx)  # → CognitiveResult
```
không phải:
```python
result = await agent.execute(task, ctx)  # bypass cognitive tier
```

**Luồng đúng sau AD-10**:
```
RequestHandler.handle(msg, ctx)
  → analyzer.analyze(msg, scope)            # IIntentAnalyzer
  → selector.select(intent, ctx)            # StrategySelector
  → ctx_routed = ctx.with_strategy(sid)     # set strategy_id trước khi dispatch
  → strategy.execute(intent, ctx_routed, pool, verifier)   # ICognitiveStrategy
      → pool.dispatch(task, ctx_routed)     # AgentPool
          → agent.execute(task, ctx_routed) # BaseAgent template
              → agent._execute(...)         # LLMAgent subclass
                  → self._react_loop(...)   # tool-call loop (internal)
```

Trade-off: thêm 1 class mới. Chấp nhận — `RequestHandler` là điểm duy nhất cần test cho cognitive routing.

### AD-11. `react_loop()` → `_react_loop()` — single-underscore signals "internal to LLMAgent._execute()"

**Decision**: Rename `LLMAgent.react_loop()` → `LLMAgent._react_loop()`. Lý do:

- `react_loop()` là **tool-call loop trong 1 agent** (LLM → tools → LLM), không phải reasoning loop của framework.
- `ReActStrategy` trong cognitive tier là **reasoning loop qua nhiều agent** — khác cấp độ.
- Public `react_loop()` hiện tại invite product code gọi thẳng từ `_execute()`, bỏ qua strategy hoàn toàn.
- Python convention: `_foo` = "internal, caller within package only" — không phải API surface của framework.

**Migration**: Các example dùng `react_loop()` → cần update `_execute()` để vẫn gọi `self._react_loop()` (vẫn OK — `_execute()` là internal của LLMAgent subclass, không phải product code bên ngoài). Đây là distinction quan trọng: product code không được gọi `react_loop()` trực tiếp, nhưng `LLMAgent._execute()` thì được gọi `self._react_loop()` vì đó là implementation của nó.

Trade-off: breaking rename — tất cả example phải update. Đánh đổi chấp nhận được, số lượng nhỏ (2 example).

### AD-12. `ExecutionContext.strategy_id: str | None` — runtime-visible proof of cognitive routing

**Decision**: Thêm field `strategy_id: str | None = None` vào `ExecutionContext`. `RequestHandler` populate field này trước khi gọi `strategy.execute()`. `BaseAgent.execute()` kiểm tra: nếu `strategy_id is None` và `enforce_cognitive_routing=True` → raise `RuntimeError`. Default `enforce_cognitive_routing=False` (warn only).

```python
# RequestHandler sets before dispatching:
ctx_routed = dataclasses.replace(ctx, strategy_id=strategy.strategy_id)
strategy.execute(intent, ctx_routed, pool, verifier)

# BaseAgent.execute() checks:
if context.strategy_id is None and self.enforce_cognitive_routing:
    raise RuntimeError(
        f"Agent {self.agent_id!r} called without cognitive routing. "
        "Use RequestHandler.handle() instead of agent.execute() directly."
    )
```

**Lý do dùng `dataclasses.replace()` thay vì mutate**: `ExecutionContext` sẽ immutable (`frozen=True`) sau AD-12 — không có side effect khi fan_out sang nhiều agents.

Trade-off: `ExecutionContext` giờ có `frozen=True` → cần `dataclasses.replace()` khi thêm field. Thêm 1 bước nhỏ khi tạo context. Chấp nhận — immutable context là pattern đúng cho concurrent fan_out.

---

## Dependency Graph

```
ICheckpointStore Protocol + Checkpoint (T01)
        │
        ├── InMemoryCheckpointStore (T01)
        │       │
        │       └── FileCheckpointStore (T05) — same Protocol contract
        │
IState Protocol + StateMachine + Workflow (T02) ─┐
        │                                        │
        ▼                                        │
IWorkflowEngine Protocol + WorkflowEngine.run() (T03)
        │                                        │
        ▼                                        │
WorkflowEngine.resume() (T04) ───────────────────┤
        │                                        │
        ▼                                        │
Contract tests (T06) ◄───────────────────────────┘
        │
        ▼
FakeCheckpointStore + FakeWorkflowEngine (T07)
        │
        ▼
Public API exports + CHANGELOG + smoke (T08)

── Phase E (cognitive routing — independent của T01-T08) ──

ExecutionContext frozen + strategy_id (T09)
        │
        ▼
RequestHandler wire (T09)  ──────────────────────────────────────────┐
        │                                                             │
        ▼                                                             │
_react_loop rename + enforce_cognitive_routing flag (T10)            │
        │                                                             │
        ▼                                                             ▼
examples migrate to RequestHandler (T10) ←── contract test routing (T10)
```

Build Phase A-D trước (T01→T08), sau đó Phase E (T09→T10). Phase E có thể làm song song với T05/T06/T07 nếu resource cho phép.

---

## Task List

### Phase A: Protocols + Foundation

---

#### Task P7-T01: `ICheckpointStore` Protocol + `InMemoryCheckpointStore`

**Description:** Spine Protocol cho checkpoint persistence + default in-memory impl. `Checkpoint` là dataclass frozen lưu state_id + output + timestamp + sequence. `InMemoryCheckpointStore` dùng dict bucket per workflow_id.

**Interface target:**

```python
# ryuu/workflow/checkpoint.py
@dataclass(frozen=True)
class Checkpoint:
    workflow_id: str
    state_id: str
    output: Any
    timestamp: float
    sequence: int                          # monotonic per workflow_id
    metadata: dict[str, Any] = field(default_factory=dict)

@runtime_checkable
class ICheckpointStore(Protocol):
    async def save(self, checkpoint: Checkpoint) -> None: ...
    async def load_latest(self, workflow_id: str) -> Checkpoint | None: ...
    async def load_history(self, workflow_id: str) -> list[Checkpoint]: ...
    async def delete(self, workflow_id: str) -> None: ...

# ryuu/workflow/stores/in_memory.py
class InMemoryCheckpointStore:
    """Dict-backed checkpoint store — no persistence. Default cho test."""
```

**Acceptance criteria:**
- [ ] `Checkpoint` là `@dataclass(frozen=True)`, có `sequence` int monotonic
- [ ] `ICheckpointStore` 4 methods async, `@runtime_checkable`
- [ ] `InMemoryCheckpointStore.save()` append vào bucket; `load_latest` return checkpoint có `sequence` cao nhất; `load_history` ordered by `sequence` ascending
- [ ] `load_latest("nonexistent")` return `None`, KHÔNG raise
- [ ] `delete(workflow_id)` xóa bucket; idempotent (xóa lần 2 không raise)
- [ ] `isinstance(InMemoryCheckpointStore(), ICheckpointStore)` = True
- [ ] mypy strict clean, ruff clean

**Verification:**
- [ ] `pytest tests/unit/workflow/test_checkpoint.py` — 8+ tests pass
- [ ] `mypy ryuu/workflow/checkpoint.py ryuu/workflow/stores/in_memory.py` — 0 errors

**Dependencies:** None

**Files:**
- `ryuu/workflow/__init__.py` (new — empty, mirror `knowledge/__init__.py`)
- `ryuu/workflow/checkpoint.py` (new — ~50 lines)
- `ryuu/workflow/stores/__init__.py` (new — empty)
- `ryuu/workflow/stores/in_memory.py` (new — ~50 lines)
- `tests/unit/workflow/__init__.py` (new — empty)
- `tests/unit/workflow/test_checkpoint.py` (new — ~120 lines)

**Estimated scope:** M (5 new files + tests)

---

#### Task P7-T02: `IState` Protocol + `Workflow` dataclass + `StateMachine`

**Description:** State graph driver. `IState` là Protocol với `state_id` + async `execute(input, context) → StateTransition`. `Workflow` là frozen dataclass định nghĩa state graph. `StateMachine` nhận `Workflow` và drive transitions, kiểm tra terminal, validate references.

**Interface target:**

```python
# ryuu/workflow/state_machine.py
@dataclass
class StateTransition:
    next_state: str | None    # None = terminal
    output: Any
    metadata: dict[str, Any] = field(default_factory=dict)

@runtime_checkable
class IState(Protocol):
    state_id: str
    async def execute(self, input: Any, context: ExecutionContext) -> StateTransition: ...

@dataclass(frozen=True)
class Workflow:
    workflow_id: str
    states: dict[str, IState]
    initial_state: str
    terminal_states: set[str]

class StateMachine:
    def __init__(self, workflow: Workflow) -> None: ...
    async def step(self, current_state_id: str, input: Any, context: ExecutionContext) -> StateTransition: ...
    def is_terminal(self, state_id: str | None) -> bool: ...
    def validate(self) -> None: ...    # raise FatalError if states reference unknown id
```

**Acceptance criteria:**
- [ ] `IState` Protocol `@runtime_checkable`
- [ ] `Workflow` là `@dataclass(frozen=True)`
- [ ] `StateMachine.step()` dispatch đến đúng `IState.execute()` + return transition
- [ ] `step()` raise `FatalError` nếu `current_state_id` không tồn tại trong workflow.states
- [ ] `is_terminal(None)` True; `is_terminal(id)` True khi id ∈ `workflow.terminal_states`
- [ ] `validate()` chạy 1 lần trước khi run — verify `initial_state` ∈ `states`, mọi state có `state_id` matching dict key
- [ ] Test với 3-state fake workflow (A→B→C, C terminal) chạy đúng
- [ ] mypy clean

**Verification:**
- [ ] `pytest tests/unit/workflow/test_state_machine.py` — 7+ tests pass
- [ ] `mypy ryuu/workflow/state_machine.py` — 0 errors

**Dependencies:** None (`Workflow` đặt trong `state_machine.py` để tránh circular import; engine import từ state_machine.)

**Files:**
- `ryuu/workflow/state_machine.py` (new — ~100 lines)
- `tests/unit/workflow/test_state_machine.py` (new — ~150 lines)

**Estimated scope:** M (2 files)

---

### ✅ Checkpoint A — Sau T01 + T02

```
pytest tests/unit/workflow/                → all pass (15+ tests)
mypy ryuu/workflow/                        → 0 errors
ruff check ryuu/workflow/ tests/unit/workflow/  → 0 violations
```

Review: foundation Protocol + state machine usable trước khi engine.

---

### Phase B: Engine Core

---

#### Task P7-T03: `IWorkflowEngine` Protocol + `WorkflowEngine.run()`

**Description:** Engine drives state machine từ initial → terminal, save checkpoint sau mỗi state, return `WorkflowResult`. Bao gồm tiered error handling (Retryable/Degraded/Fatal). KHÔNG có resume — defer T04.

**Interface target:**

```python
# ryuu/workflow/engine.py
class WorkflowStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"          # for future resume

@dataclass
class WorkflowResult:
    workflow_id: str
    status: WorkflowStatus
    final_state: str | None
    output: Any
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    checkpoints_saved: int = 0

@runtime_checkable
class IWorkflowEngine(Protocol):
    async def run(self, workflow: Workflow, initial_input: Any, context: ExecutionContext) -> WorkflowResult: ...
    async def resume(self, workflow_id: str, workflow: Workflow, context: ExecutionContext) -> WorkflowResult: ...

@dataclass
class WorkflowEngine:
    checkpoint_store: ICheckpointStore
    max_state_retries: int = 3
    max_transitions: int = 1000          # safety cap on infinite loops

    async def run(self, workflow, initial_input, context) -> WorkflowResult:
        # 1. machine = StateMachine(workflow); machine.validate()
        # 2. current_state = workflow.initial_state, input = initial_input, sequence = 0
        # 3. while not is_terminal:
        #      attempt = 0
        #      while attempt < max_state_retries:
        #          try: transition = await machine.step(...); break
        #          except RetryableError as e:
        #              decision = retry_policy(e, attempt); await anyio.sleep(decision.wait_seconds); attempt += 1
        #          except DegradedError: log; break  # continue with whatever state has
        #          except FatalError: return WorkflowResult(status=FAILED, error=str(exc))
        #      else: return WorkflowResult(status=FAILED, error="max retries exceeded")
        #      checkpoint = Checkpoint(workflow_id, current_state, transition.output, time.time(), sequence,
        #                              metadata={"next_state": transition.next_state})
        #      await checkpoint_store.save(checkpoint); sequence += 1
        #      current_state = transition.next_state; input = transition.output
        #      transitions += 1; if transitions > max_transitions: FAILED("loop detected")
        # 4. return WorkflowResult(status=COMPLETED, final_state, output, checkpoints_saved=sequence)
```

**Acceptance criteria:**
- [ ] `WorkflowEngine.run()` execute tất cả states từ `initial_state` đến terminal
- [ ] Sau mỗi state, save 1 `Checkpoint` qua `checkpoint_store.save()`, metadata có `next_state`
- [ ] `WorkflowResult.status == COMPLETED` khi reach terminal
- [ ] `WorkflowResult.checkpoints_saved` count đúng số states đã run
- [ ] `RetryableError` từ state → retry với `retry_policy()` backoff, tối đa `max_state_retries` lần
- [ ] Sau `max_state_retries` thất bại → `WorkflowResult(status=FAILED, error="...")`, KHÔNG raise
- [ ] `FatalError` từ state → dừng ngay, `WorkflowResult(status=FAILED)`
- [ ] `DegradedError` → log warning, **break attempt loop và tiếp tục với output hiện có** (không retry, không fail)
- [ ] Loop safety: nếu `max_transitions` exceeded → FAILED với error="max transitions exceeded"
- [ ] `isinstance(WorkflowEngine(...), IWorkflowEngine)` = True
- [ ] mypy clean

**Verification:**
- [ ] `pytest tests/unit/workflow/test_engine_run.py` — 12+ tests pass
- [ ] Cover: happy path, RetryableError → retry → success, RetryableError exhausted → FAILED, FatalError → FAILED, DegradedError → continue, max_transitions cap, terminal-as-initial-state
- [ ] `mypy ryuu/workflow/engine.py` — 0 errors

**Dependencies:** T01 (ICheckpointStore), T02 (StateMachine + IState + Workflow)

**Files:**
- `ryuu/workflow/engine.py` (new — ~200 lines, gồm `WorkflowStatus`, `WorkflowResult`, `IWorkflowEngine`, `WorkflowEngine`)
- `tests/unit/workflow/test_engine_run.py` (new — ~250 lines)

**Estimated scope:** M (2 files)

---

#### Task P7-T04: `WorkflowEngine.resume()` — SIGKILL-safe recovery

**Description:** Resume workflow từ checkpoint mới nhất. Nếu `load_latest(workflow_id)` return None → start từ initial. Nếu trả về checkpoint → tiếp tục từ `metadata["next_state"]` của checkpoint với output làm input. Refactor `run()` để share inner loop với `resume()`.

**Interface target:**

```python
async def resume(
    self,
    workflow_id: str,
    workflow: Workflow,
    context: ExecutionContext,
) -> WorkflowResult:
    checkpoint = await self.checkpoint_store.load_latest(workflow_id)
    if checkpoint is None:
        return await self.run(workflow, initial_input=None, context=context)
    next_state = checkpoint.metadata.get("next_state")
    if next_state is None:    # last checkpoint was terminal
        return WorkflowResult(workflow_id, status=COMPLETED,
                              final_state=checkpoint.state_id, output=checkpoint.output,
                              checkpoints_saved=checkpoint.sequence + 1)
    # resume from next_state with checkpoint.output as input, sequence = checkpoint.sequence + 1
```

**Acceptance criteria:**
- [ ] `resume("nonexistent_id", ...)` start từ `workflow.initial_state` (gọi internal run path)
- [ ] `resume(workflow_id, ...)` với 1 checkpoint đã save → tiếp tục từ `metadata["next_state"]` với input = checkpoint.output
- [ ] Resume sau 2 states → 1 state tiếp + checkpoint thứ 3 → final result đúng
- [ ] Resume sau khi reach terminal → return COMPLETED ngay, không re-run
- [ ] Resume khi checkpoint cuối có `next_state` reference unknown state → FAILED với error rõ
- [ ] `sequence` số tiếp tục từ `checkpoint.sequence + 1`, không reset về 0
- [ ] mypy clean

**Verification:**
- [ ] `pytest tests/unit/workflow/test_engine_resume.py` — 8+ tests pass
- [ ] Cover: resume from each state, resume on no-checkpoint, resume after terminal, resume on broken next_state, sequence continuity
- [ ] `mypy ryuu/workflow/engine.py` — 0 errors

**Dependencies:** T03

**Files:**
- `ryuu/workflow/engine.py` (extend với resume + refactor run() để share inner loop)
- `tests/unit/workflow/test_engine_resume.py` (new — ~180 lines)

**Estimated scope:** M (2 files; engine.py extend ~50 lines)

---

### ✅ Checkpoint B — Sau T03 + T04

```
pytest tests/unit/workflow/                → all pass (35+ tests)
mypy ryuu/                                  → 0 errors
ruff check ryuu/ tests/                    → 0 violations
coverage ryuu/workflow/engine.py           → ≥ 90%
coverage ryuu/workflow/state_machine.py    → ≥ 90%
```

**Human review required**: API surface (`IWorkflowEngine`, `Workflow`, `IState`, `ICheckpointStore`) lock trước khi proceed Phase C — đây là stable contract product team sẽ depend.

---

### Phase C: Persistence + Contract Tests

---

#### Task P7-T05: `FileCheckpointStore` — JSON-on-disk persistence

**Description:** ICheckpointStore impl ghi xuống disk. Mỗi workflow_id = 1 thư mục, mỗi checkpoint = 1 file JSON `<sequence>.json`. SIGKILL-safe vì state đã flush trước khi process die. Atomic write qua tmpfile + os.replace.

**Interface target:**

```python
# ryuu/workflow/stores/file.py
class FileCheckpointStore:
    """JSON-file-backed checkpoint store. Output must be JSON-serializable.

    Layout:
        <base_dir>/<workflow_id>/<sequence>.json

    Atomic write: write to .tmp, then os.replace(.tmp, .json).
    """
    def __init__(self, base_dir: Path) -> None: ...

    async def save(self, checkpoint: Checkpoint) -> None:
        # 1. Ensure dir exists
        # 2. Try json.dumps(checkpoint dict) → raise FatalError if not serializable
        # 3. Write atomically: tmp file → os.replace
    async def load_latest(self, workflow_id: str) -> Checkpoint | None: ...
    async def load_history(self, workflow_id: str) -> list[Checkpoint]: ...
    async def delete(self, workflow_id: str) -> None: ...
```

**Acceptance criteria:**
- [ ] `save()` write file atomically (tmpfile → rename) — corrupt write không xảy ra với SIGKILL
- [ ] Output không JSON-serializable → raise `FatalError` với message rõ
- [ ] `load_latest()` đọc file có `sequence` cao nhất; return None nếu thư mục trống/không tồn tại
- [ ] `load_history()` return list ordered by sequence ascending
- [ ] `delete()` xóa toàn bộ workflow_id directory; idempotent
- [ ] Round-trip test: save → load_latest → equal Checkpoint object (qua tmp_path fixture)
- [ ] Cross-process simulation: store A save → store B (fresh init same base_dir) load — kết quả match
- [ ] `isinstance(FileCheckpointStore(tmp_path), ICheckpointStore)` = True
- [ ] mypy clean

**Verification:**
- [ ] `pytest tests/unit/workflow/stores/test_file.py` — 10+ tests pass
- [ ] `mypy ryuu/workflow/stores/file.py` — 0 errors

**Dependencies:** T01

**Files:**
- `ryuu/workflow/stores/file.py` (new — ~100 lines)
- `tests/unit/workflow/stores/__init__.py` (new — empty)
- `tests/unit/workflow/stores/test_file.py` (new — ~180 lines)

**Estimated scope:** M (3 files)

---

#### Task P7-T06: Contract tests cho `ICheckpointStore` + `IWorkflowEngine`

**Description:** Parametric contract tests đảm bảo mọi impl của Protocol pass cùng 1 spec — bắt drift sớm khi product team viết custom impl.

**Interface target:**

```python
# tests/contract/test_workflow_contract.py

@pytest.fixture(params=["in_memory", "file"])
def checkpoint_store(request, tmp_path):
    if request.param == "in_memory":
        return InMemoryCheckpointStore()
    return FileCheckpointStore(tmp_path)

class TestCheckpointStoreContract:
    async def test_save_then_load_latest_returns_saved(self, checkpoint_store): ...
    async def test_load_latest_on_empty_returns_none(self, checkpoint_store): ...
    async def test_load_history_ordered_by_sequence(self, checkpoint_store): ...
    async def test_delete_idempotent(self, checkpoint_store): ...
    async def test_isolation_between_workflow_ids(self, checkpoint_store): ...

class TestWorkflowEngineContract:
    async def test_run_completes_simple_3_state_workflow(self, engine): ...
    async def test_resume_after_partial_run_completes(self, engine): ...
    async def test_fatal_error_results_in_failed_status(self, engine): ...
```

**Acceptance criteria:**
- [ ] `TestCheckpointStoreContract`: 5+ tests, parametrize qua `InMemoryCheckpointStore` + `FileCheckpointStore` → tất cả pass cho cả 2
- [ ] `TestWorkflowEngineContract`: 3+ tests dùng `WorkflowEngine` + each store impl
- [ ] Test discover xem isinstance Protocol — fail rõ nếu impl thiếu method
- [ ] mypy clean

**Verification:**
- [ ] `pytest tests/contract/test_workflow_contract.py -v` — tất cả pass
- [ ] Output có 2 entry per test (in_memory + file)

**Dependencies:** T01, T03, T04, T05

**Files:**
- `tests/contract/test_workflow_contract.py` (new — ~200 lines)

**Estimated scope:** S (1 file)

---

### ✅ Checkpoint C — Sau T05 + T06

```
pytest tests/                              → all pass (525+ tests)
mypy ryuu/ tests/                          → 0 errors
ruff check ryuu/ tests/                    → 0 violations
coverage ryuu/workflow/                    → ≥ 90%
```

---

### Phase D: Public API + Test Utilities + Ship

---

#### Task P7-T07: `FakeCheckpointStore` + `FakeWorkflowEngine` trong `_testing/fakes.py`

**Description:** Fakes cho product team test workflow definitions mà không đụng disk. `FakeCheckpointStore` thin wrapper với tracking counters; `FakeWorkflowEngine` deterministic runner.

**Interface target:**

```python
# ryuu/_testing/fakes.py (extend)

class FakeCheckpointStore:
    """Tracking wrapper around dict-backed store for tests."""
    def __init__(self) -> None:
        self._data: dict[str, list[Checkpoint]] = {}
        self.save_count = 0
        self.load_count = 0
    async def save(self, checkpoint: Checkpoint) -> None: ...
    async def load_latest(self, workflow_id: str) -> Checkpoint | None: ...
    async def load_history(self, workflow_id: str) -> list[Checkpoint]: ...
    async def delete(self, workflow_id: str) -> None: ...

class FakeWorkflowEngine:
    """Deterministic IWorkflowEngine: returns pre-canned WorkflowResult."""
    def __init__(self, results: list[WorkflowResult] | None = None) -> None: ...
    async def run(self, workflow, initial_input, context) -> WorkflowResult: ...
    async def resume(self, workflow_id, workflow, context) -> WorkflowResult: ...
```

**Acceptance criteria:**
- [ ] `FakeCheckpointStore` implement đầy đủ `ICheckpointStore` Protocol
- [ ] Có `save_count`, `load_count` counter cho assertion trong test
- [ ] `FakeWorkflowEngine` pop từ pre-canned queue; default trả `WorkflowResult(status=COMPLETED, ...)`
- [ ] `isinstance(FakeCheckpointStore(), ICheckpointStore)` = True
- [ ] `isinstance(FakeWorkflowEngine(), IWorkflowEngine)` = True
- [ ] mypy clean

**Verification:**
- [ ] `pytest tests/unit/_testing/test_workflow_fakes.py` — 6+ tests pass
- [ ] `mypy ryuu/_testing/fakes.py` — 0 errors

**Dependencies:** T01, T03

**Files:**
- `ryuu/_testing/fakes.py` (extend ~60 lines)
- `tests/unit/_testing/test_workflow_fakes.py` (new — ~80 lines)

**Estimated scope:** S (2 files)

---

#### Task P7-T08: Integration smoke + public API exports + CHANGELOG + version bump

**Description:** Integration test end-to-end (3-state workflow + FileCheckpointStore + simulate SIGKILL via fresh engine instance). Update `ryuu/__init__.py` re-exports. CHANGELOG entry + version bump 0.1.0b6 → 0.1.0b7. Project memory update.

**Acceptance criteria:**
- [ ] `tests/integration/test_phase7_smoke.py`:
  - Workflow 3-state (PARSE → ENRICH → DERIVE), mỗi state là `IState` impl
  - Run full workflow → status=COMPLETED, 3 checkpoints saved
  - Simulate crash: tạo engine A, run đến state 2 (raise crash giả), tạo engine B fresh + same FileCheckpointStore, resume → completes
- [ ] `ryuu/__init__.py` exports:
  - `Workflow`, `WorkflowEngine`, `IWorkflowEngine`, `WorkflowResult`, `WorkflowStatus`
  - `IState`, `StateMachine`, `StateTransition`
  - `Checkpoint`, `ICheckpointStore`, `InMemoryCheckpointStore`, `FileCheckpointStore`
- [ ] Version bump `__version__` trong `ryuu/__init__.py`: `0.1.0b6` → `0.1.0b7` (pyproject hiện vẫn `0.1.0a1` — confirm path bump trong T08 thực tế)
- [ ] CHANGELOG entry `[0.1.0b7] - 2026-05-08` mô tả Phase 7 changes
- [ ] Update `memory/project_phase7_status.md` (mới)
- [ ] `python -c "from ryuu import WorkflowEngine, Workflow, IState, ICheckpointStore"` — no ImportError

**Verification:**
- [ ] `pytest tests/integration/test_phase7_smoke.py -v` — pass
- [ ] `python -c "from ryuu import WorkflowEngine"` exits 0

**Dependencies:** T01-T07 (all)

**Files:**
- `tests/integration/test_phase7_smoke.py` (new — ~150 lines)
- `ryuu/__init__.py` (extend ~12 exports)
- `pyproject.toml` (confirm version)
- `CHANGELOG.md` (extend)
- `memory/project_phase7_status.md` (new — claude-mem)

**Estimated scope:** M (5 files)

---

### Phase E: Cognitive Pipeline Wiring (lấp gap RequestHandler)

> **Mục tiêu**: Lấp gap giữa `ICognitiveStrategy` đã có và product code đang bypass nó. Hai task này **độc lập với T01-T08** — có thể làm song song với Phase C/D.

---

#### Task P7-T09: `ExecutionContext` frozen + `strategy_id` field + `RequestHandler`

**Description:** Hai thay đổi đi cùng nhau:
1. `ExecutionContext` đổi thành `frozen=True`, thêm field `strategy_id: str | None = None`.
2. `RequestHandler` — dataclass wire `IIntentAnalyzer → StrategySelector → ICognitiveStrategy.execute()`, set `strategy_id` trước khi dispatch.

**Interface target:**

```python
# ryuu/runtime/context.py — thay đổi
@dataclass(frozen=True)              # WAS: @dataclass (mutable)
class ExecutionContext:
    scope: ContextScope
    correlation_id: str
    budget_remaining_usd: float | None = None
    strategy_id: str | None = None   # NEW: populated by RequestHandler

# ryuu/runtime/request_handler.py — mới
@dataclass
class RequestHandler:
    """Single entry point for conversational mode.

    Wires: analyzer → selector → strategy.execute(intent, ctx_routed, pool, verifier)

    Product code calls handle(), NOT agent.execute() directly.
    """
    analyzer: IIntentAnalyzer
    selector: StrategySelector
    pool: AgentPool
    verifier: IVerifier

    async def handle(
        self,
        message: str,
        context: ExecutionContext,
    ) -> CognitiveResult:
        intent = await self.analyzer.analyze(message, context.scope)
        strategy = self.selector.select(intent, context)
        # Immutable replace — new context carries strategy_id proof
        ctx_routed = dataclasses.replace(context, strategy_id=strategy.strategy_id)
        return await strategy.execute(intent, ctx_routed, self.pool, self.verifier)
```

**Acceptance criteria:**
- [ ] `ExecutionContext` là `@dataclass(frozen=True)` — `ctx.strategy_id = "x"` raise `FrozenInstanceError`
- [ ] `ExecutionContext.strategy_id` default `None`; `dataclasses.replace(ctx, strategy_id="react")` tạo bản copy với field mới
- [ ] `RequestHandler.handle()` flow đúng: analyze → select → `ctx_routed.strategy_id == strategy.strategy_id` → strategy.execute
- [ ] `RequestHandler` không import bất kỳ concrete agent nào — chỉ phụ thuộc vào Protocols
- [ ] Test: `handle()` với `FakeIntentAnalyzer` + `FakeAgentPool` + `FakeVerifier` → `CognitiveResult` đúng
- [ ] Test: `strategy_id` trên `ctx_routed` match `strategy.strategy_id` được dispatch
- [ ] Test: original `context` không bị mutate (frozen verify bằng id check)
- [ ] `isinstance(ctx_routed, ExecutionContext)` = True
- [ ] mypy clean — `frozen=True` bắt mọi assignment accident

**Breaking change cần xử lý:**
- `ExecutionContext` hiện là mutable → các test dùng `ctx.budget_remaining_usd = x` phải đổi sang `dataclasses.replace(ctx, budget_remaining_usd=x)`. Số lượng nhỏ — scan trước khi start.

**Verification:**
- [ ] `pytest tests/unit/runtime/test_request_handler.py` — 8+ tests pass
- [ ] `pytest tests/unit/runtime/test_context.py` — update + thêm frozen tests — all pass
- [ ] `mypy ryuu/runtime/` — 0 errors
- [ ] `grep -rn "ExecutionContext(" tests/ ryuu/ examples/` — audit không còn dùng mutate pattern

**Dependencies:** P1 (IIntentAnalyzer), P1 (StrategySelector), P6 (AgentPool), P2 (ICognitiveStrategy, IVerifier)

**Files:**
- `ryuu/runtime/context.py` (modify — frozen=True + strategy_id field, ~5 lines)
- `ryuu/runtime/request_handler.py` (new — ~80 lines)
- `tests/unit/runtime/test_request_handler.py` (new — ~150 lines)
- `tests/unit/runtime/test_context.py` (modify — add frozen assertions, ~+20 lines)
- Scan + fix toàn bộ test files đang mutate `ExecutionContext`

**Estimated scope:** M (3 files new + scan existing)

---

#### Task P7-T10: `_react_loop()` rename + `enforce_cognitive_routing` + examples migrate

**Description:** Ba thay đổi nhỏ đi cùng nhau làm rõ ranh giới kiến trúc:
1. Rename `LLMAgent.react_loop()` → `LLMAgent._react_loop()` — single underscore = internal to `_execute()`.
2. Thêm `enforce_cognitive_routing: bool = False` vào `BaseAgent` — khi `True` + `context.strategy_id is None` → raise `RuntimeError`.
3. Update `todo_app` + `stock_advisory` examples để show 2 path: direct (current, learning) và routed (via RequestHandler).

**Interface target:**

```python
# ryuu/execution/llm_agent.py
class LLMAgent(BaseAgent):
    # ...
    async def _react_loop(          # WAS: react_loop (public)
        self,
        request: CompletionRequest,
        max_rounds: int = 3,
        domain: str = "",
        callbacks: ReActCallbacks | None = None,
    ) -> tuple[str, TokenUsage]: ...

# ryuu/execution/agent.py
@dataclass
class BaseAgent(ABC):
    # ...
    enforce_cognitive_routing: bool = False   # NEW field

    async def execute(self, task: Task, context: ExecutionContext) -> AgentResult:
        # NEW: check routing proof
        if self.enforce_cognitive_routing and context.strategy_id is None:
            raise RuntimeError(
                f"Agent {self.agent_id!r} called without cognitive routing "
                "(context.strategy_id is None). "
                "Use RequestHandler.handle() or set enforce_cognitive_routing=False "
                "for direct-call patterns (tests, examples)."
            )
        # ... existing template method unchanged
```

**Tại sao `enforce_cognitive_routing=False` mặc định:**
- Breaking default sẽ làm vỡ toàn bộ example + existing tests → không chấp nhận được.
- `False` = "opt-in enforcement" — HIGH trust domains (stock trading) bật `True` khi deploy production.
- `True` trong integration test smoke của `RequestHandler` để prove routing works end-to-end.

**Example update strategy** — KHÔNG xóa direct-call pattern vì mục đích learning, thay vào đó:
```python
# examples/stock_advisory/main.py — Case 2 sau khi update
# ── Path A: direct (learning — gọi thẳng agent, bypass strategy) ────
result = await agent.execute(task, ctx_direct)

# ── Path B: routed (production — qua RequestHandler + cognitive tier) ─
handler = RequestHandler(analyzer=LLMIntentAnalyzer(...), selector=..., pool=pool, verifier=...)
result = await handler.handle(message=query, context=ctx)
```

**Acceptance criteria:**
- [ ] `LLMAgent._react_loop()` đổi tên — tất cả internal call (`self.react_loop(...)` trong `_execute()`) đổi sang `self._react_loop(...)`
- [ ] `LLMAgent.react_loop` không còn tồn tại — mypy sẽ bắt nếu code nào còn gọi
- [ ] `BaseAgent.enforce_cognitive_routing: bool = False` — không breaking default
- [ ] `BaseAgent.execute()` raise `RuntimeError` khi `enforce_cognitive_routing=True` và `context.strategy_id is None`
- [ ] `BaseAgent.execute()` KHÔNG raise khi `enforce_cognitive_routing=False` (default) — backward compat
- [ ] `BaseAgent.execute()` KHÔNG raise khi `enforce_cognitive_routing=True` và `context.strategy_id` có giá trị
- [ ] Test: enforce=True + ctx không có strategy_id → RuntimeError với message hữu ích
- [ ] Test: enforce=True + ctx có strategy_id → execute proceeds bình thường
- [ ] `examples/stock_advisory/main.py` thêm comment + Path B demo dùng `RequestHandler`
- [ ] `examples/todo_app/main.py` thêm comment giải thích tradeoff direct vs routed
- [ ] mypy clean sau rename — 0 errors

**Verification:**
- [ ] `pytest tests/unit/execution/test_base_agent.py` — thêm 3+ test cho enforce flag — all pass
- [ ] `pytest tests/` — toàn bộ existing tests pass sau `_react_loop` rename (không regression)
- [ ] `grep -rn "\.react_loop(" ryuu/ examples/ tests/` → 0 kết quả (tất cả đã đổi sang `._react_loop(`)
- [ ] `grep -rn "\._react_loop(" ryuu/execution/llm_agent.py` → có (đây là chỗ duy nhất được dùng)
- [ ] `mypy ryuu/` — 0 errors

**Dependencies:** T09 (ExecutionContext frozen + strategy_id)

**Files:**
- `ryuu/execution/llm_agent.py` (modify — rename react_loop → _react_loop, ~3 lines)
- `ryuu/execution/agent.py` (modify — thêm enforce_cognitive_routing field + check, ~10 lines)
- `examples/todo_app/agent.py` (modify — self.react_loop → self._react_loop)
- `examples/stock_advisory/agent.py` (modify — self.react_loop → self._react_loop)
- `examples/stock_advisory/main.py` (modify — thêm Path B demo dùng RequestHandler)
- `tests/unit/execution/test_base_agent.py` (modify — thêm enforce tests, ~+40 lines)
- `tests/unit/execution/test_llm_agent.py` (modify — rename refs, ~minimal)

**Estimated scope:** S (nhiều files nhỏ, thay đổi cục bộ mỗi file)

---

### ✅ Checkpoint E — Sau T09 + T10

```
pytest tests/                                      → all pass (550+ tests)
mypy ryuu/                                         → 0 errors
grep -rn "\.react_loop(" ryuu/ examples/ tests/   → 0 results (renamed)
grep -rn "strategy_id" ryuu/runtime/              → có trong context.py + request_handler.py
python3 -m examples.stock_advisory.main --case 2  → chạy được (Path A direct + Path B routed)
```

---

### ✅ Final CI Gate — Phase 7 Complete

```bash
ruff check ryuu/ tests/ examples/                              → 0 violations
mypy ryuu/                                                     → 0 errors
pytest tests/ --cov=ryuu --cov-fail-under=88                  → 550+ pass, ≥88% coverage ✅
python -c "from ryuu import WorkflowEngine, Workflow, IState, ICheckpointStore, FileCheckpointStore, RequestHandler"   → no ImportError ✅
grep -r "asyncio.gather" ryuu/                                 → no results ✅
grep -r "import asyncio" ryuu/workflow/                        → no results ✅ (chỉ anyio)
grep -rn "\.react_loop(" ryuu/ examples/ tests/               → 0 results ✅ (renamed to _react_loop)
grep -rn "strategy_id" ryuu/runtime/context.py                → có ✅ (field tồn tại)
```

---

## New Files Summary

| File | Type | Est. Lines |
|------|------|-----------|
| `ryuu/workflow/__init__.py` | new | 0 (empty) |
| `ryuu/workflow/checkpoint.py` | new | ~50 |
| `ryuu/workflow/state_machine.py` | new | ~100 |
| `ryuu/workflow/engine.py` | new | ~200 |
| `ryuu/workflow/stores/__init__.py` | new | 0 (empty) |
| `ryuu/workflow/stores/in_memory.py` | new | ~50 |
| `ryuu/workflow/stores/file.py` | new | ~100 |
| `tests/unit/workflow/__init__.py` | new | 0 |
| `tests/unit/workflow/test_checkpoint.py` | new | ~120 |
| `tests/unit/workflow/test_state_machine.py` | new | ~150 |
| `tests/unit/workflow/test_engine_run.py` | new | ~250 |
| `tests/unit/workflow/test_engine_resume.py` | new | ~180 |
| `tests/unit/workflow/stores/__init__.py` | new | 0 |
| `tests/unit/workflow/stores/test_file.py` | new | ~180 |
| `tests/contract/test_workflow_contract.py` | new | ~200 |
| `tests/unit/_testing/test_workflow_fakes.py` | new | ~80 |
| `tests/integration/test_phase7_smoke.py` | new | ~150 |
| `ryuu/_testing/fakes.py` | modify | +60 |
| `ryuu/__init__.py` | modify | +12 exports |
| `pyproject.toml` | modify | version bump |
| `CHANGELOG.md` | modify | +1 entry |
| `memory/project_phase7_status.md` | new (claude-mem) | small |

**Phase E (cognitive routing):**

| File | Type | Est. Lines |
|------|------|-----------|
| `ryuu/runtime/context.py` | modify | +5 (frozen + strategy_id) |
| `ryuu/runtime/request_handler.py` | new | ~80 |
| `tests/unit/runtime/test_request_handler.py` | new | ~150 |
| `tests/unit/runtime/test_context.py` | modify | +20 (frozen tests) |
| `ryuu/execution/agent.py` | modify | +10 (enforce_cognitive_routing) |
| `ryuu/execution/llm_agent.py` | modify | ~3 (rename) |
| `examples/todo_app/agent.py` | modify | ~3 (rename call) |
| `examples/stock_advisory/agent.py` | modify | ~3 (rename call) |
| `examples/stock_advisory/main.py` | modify | +20 (Path B demo) |
| `tests/unit/execution/test_base_agent.py` | modify | +40 (enforce tests) |
| `tests/unit/execution/test_llm_agent.py` | modify | ~5 (rename refs) |

**Total new prod code (Phase A-D + E)**: ~600 LOC. **Total new test code**: ~1570 LOC. **Test/code ratio**: ~2.6x.

---

## Risks and Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|------------|------------|
| Output không JSON-serializable trong FileCheckpointStore | Medium | High | Document constraint trong docstring; raise `FatalError` với message rõ trong save(); test case explicit cho "non-serializable raises" |
| Atomic write trên Windows (os.replace semantics) | Low | Low | `os.replace` đã atomic trên Windows từ Py 3.3; document; nếu cần thêm Windows-specific test có thể defer |
| Resume race khi 2 process dùng cùng FileCheckpointStore | Medium | Low | Out-of-scope v0.1; document "single-writer per workflow_id"; ghi rõ trong CHANGELOG |
| State graph cycle / infinite loop | Medium | Medium | `max_transitions=1000` cap trong WorkflowEngine; FAILED với error rõ |
| `Workflow.states[id].next_state` ref đến state không tồn tại | Medium | Medium | `StateMachine.validate()` quét trước khi run; raise `FatalError` ngay |
| Checkpoint sequence collision khi resume + run cùng workflow_id | Low | Low | Sequence từ `load_latest().sequence + 1` khi resume; test explicit cho continuity |
| Test với `tmp_path` flake trên CI nếu cleanup không kịp | Low | Low | Pytest `tmp_path` fixture tự cleanup; không lưu state ngoài fixture scope |
| Coverage giảm vì thêm 500 LOC mà test chưa kịp 90% | Low | Medium | Gate Checkpoint B + C explicit check coverage `ryuu/workflow/` ≥ 90% trước khi proceed |

---

## Open Questions

> Trả lời trước khi start T01, hoặc đính kèm note "deferred" rõ ràng.

1. **Cancellation semantics** — Engine có support `anyio.move_on_after()` cancellation không? Nếu user gọi `await engine.run(...)` rồi cancel, behavior gì? **Default v0.1**: cooperative cancellation only — anyio task tự cancel; engine không phải làm gì đặc biệt; test `cancel mid-state` defer Phase 8.

2. **Logging integration** — Engine có nên log mỗi transition qua `Tracer` không? **Default**: không trong v0.1. State (qua agent) đã log qua BaseAgent template. Engine-level tracing có thể thêm sau.

3. **`WorkflowResult.output` semantic** — Engine return `WorkflowResult.output = transition.output` của terminal state. **Default**: yes; rõ ràng.

4. **`ICheckpointStore.save()` thread/async safety** — InMemoryCheckpointStore dùng plain dict. Concurrent saves từ multiple workflows OK vì keyed by workflow_id; same workflow_id concurrent saves là user error. **Default**: không lock; document "single-writer per workflow_id".

5. **`RYUURuntime.run_workflow()` façade** — Có nên thêm vào `runtime/runtime.py` không? **Decision**: defer Phase 8 — runtime façade chưa có form rõ; product hiện gọi `WorkflowEngine` trực tiếp. `RequestHandler` (T09) lấp gap conversational mode trước.

7. **`RequestHandler` — clarification flow** — Khi `intent.ambiguous == True`, `RequestHandler` có nên tự trigger clarification (gọi `IIntentAnalyzer` lần 2 với clarification questions) không? **Default v0.1**: không — `RequestHandler.handle()` trả về `CognitiveResult` với content từ strategy, kể cả khi intent mơ hồ. Clarification auto-trigger là Phase 8 (spec §intent/clarification.py đã có skeleton nhưng chưa wire).

8. **`enforce_cognitive_routing` scope** — `enforce_cognitive_routing=True` nên đặt ở BaseAgent (per-agent) hay trên `AgentPool` (per-pool) hay `RequestHandler` (per-handler)? **Default v0.1**: per-agent field. Stock trading agent production config sẽ set `enforce_cognitive_routing=True`; test/example agents dùng `False`. Pool-level enforcement có thể thêm sau nếu cần fleet control.

9. **`react_loop()` alias trong transition window** — Có nên giữ deprecated alias `react_loop = _react_loop` trong 1 version không? **Decision**: không — alias invite continued wrong usage và mypy sẽ không bắt được. Breaking ngay + fix trong cùng PR T10. Số lượng callsite nhỏ (2 example agents).

6. **DegradedError continuation behavior** — AD-6 nói "tiếp tục với output hiện có". Nhưng `output` của state failed là gì? **Default**: state phải tự return partial output trước khi raise DegradedError, hoặc engine treat như RetryableError thông thường. **Refinement**: chỉ catch DegradedError nếu nó có `partial_output` attribute (custom); fallback = raise FatalError. Decision: defer — viết test sau khi có concrete use case.

---

## Parallelization Opportunities

- **Sequential strict**: T01 → T02 → T03 → T04 (engine builds on state machine + checkpoint).
- **Có thể parallel sau Checkpoint B**:
  - T05 (FileCheckpointStore) ⇄ T07 (Fakes) độc lập với nhau — viết song song.
  - T06 (Contract tests) cần T05 — chạy sau.
- **T08 strict cuối**: cần tất cả prior tasks done.

---

## Verification Checklist (planning skill)

- [x] Mỗi task có acceptance criteria specific + testable
- [x] Mỗi task có verification step (pytest command, mypy command)
- [x] Dependencies map rõ + order đúng (T01 → T02 → T03 → T04 → T05/T06/T07 → T08; T09 → T10 independent)
- [x] Không task nào touch >5 files (max là T08 = 5 files; T10 = 7 files nhưng đa phần chỉ rename — acceptable)
- [x] Có 4 checkpoints (A, B, C, E) + Final CI Gate
- [x] Architecture decisions explicit (12 ADs — bổ sung AD-10/11/12 cho cognitive routing)
- [x] Risks + open questions surface (9 OQs)
- [x] Vertical slicing: mỗi task deliver complete vertical
- [x] Gap đã được lấp: `RequestHandler` wire intent → strategy → pool → agent; `_react_loop` rename signal boundary

---

**Status**: Plan updated 2026-05-08. Phase A-D ready to implement. Phase E (T09-T10) ready. Awaiting human approval trước khi T01 bắt đầu.
