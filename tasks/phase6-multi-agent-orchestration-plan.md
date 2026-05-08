# Implementation Plan: Phase 6 — Multi-Agent Orchestration

## Overview

Nâng multi-agent từ "DIY ở tầng application" lên **framework-level feature**. Hiện tại `IAgentPool` Protocol đã có nhưng không có concrete implementation; `examples/code_analysis` dùng `asyncio.gather()` trực tiếp — vi phạm spec anyio.

Phase 6 xây **2 framework components**: `AgentPool` (registry + routing + bounded concurrency + partial failure modes) và `ParallelFanoutStrategy` (ICognitiveStrategy thứ 4). Sau đó refactor examples sang dùng AgentPool thay `asyncio.gather`.

> **Note — OrchestratorAgent removed (Fix #5):** Expert review xác định `OrchestratorAgent` duplicate với `ParallelFanoutStrategy` (cùng flow: decompose → fan_out → aggregate) và không có use case framework cụ thể để justify. Không thêm vào framework core. Nếu product cần supervisor pattern, viết ở `examples/` level như `CodebaseAnalysisOrchestrator` hiện tại. Xem [Resolved Decisions](#resolved-decisions).

Scope KHÔNG bao gồm: `uaaf/workflow/` (WorkflowEngine + StateMachine + Checkpoint) — để lại Phase 7.

**CI gate đầu vào (Phase 5):** ruff ✓, mypy ✓, 383 tests pass, 91.48% coverage.

---

## Architecture Decisions

- **anyio task group, KHÔNG asyncio.gather** — spec tại §5 cấm `import asyncio` trong `uaaf/`; `anyio.create_task_group()` là primitive đúng.
- **AgentPool là dataclass, không phải singleton** — caller tự quản lý lifecycle; testable, injectable.
- **`dispatch()` dùng round_robin routing, KHÔNG "first registered"** — "first registered" là silent bug magnet: 10 agents trong pool, luôn chọn 1 agent không có fail. Round_robin predictable hơn dưới load, random là option thứ 2. Caller cần default routing explicit, hoặc dùng `dispatch_to()` (exact) / `fan_out()` (broadcast). Fix #7 từ expert review.
- **`fan_out` có `on_error` mode — fail_fast vs collect** — `anyio.create_task_group()` mặc định cancel tất cả task khi 1 task fail (fail_fast). `collect` mode dùng per-task `CancelScope` để giữ partial results — phù hợp cho `ParallelFanoutStrategy` cần aggregate kết quả từ N workers. Fix #6 từ expert review.
- **`fan_out` là method riêng, không phải overload của `dispatch`** — signature rõ ràng, tránh ambiguity.
- **ParallelFanoutStrategy là ICognitiveStrategy thứ 4** — cùng contract với Direct/ReAct/EvaluatorOptimizer; StrategySelector có thể chọn nó khi complexity=HIGH.
- **OrchestratorAgent deferred** — không implement trong framework core Phase 6. Xem note trên.

---

## Dependency Graph

```
IAgentPool Protocol (đã có)
    │
    └── AgentPool (T01) ← foundation của mọi thứ
            │
            ├── ParallelFanoutStrategy (T03) — dùng pool.fan_out(on_error="collect")
            │       │
            │       └── Contract test update (T03)
            │
            └── examples/code_analysis refactor (T06) — replace asyncio.gather
```

Build từ bottom: T01 → T02 → T03 → Checkpoint B → T06 → T07 → T08.

---

## Task List

### Phase A: AgentPool Foundation

---

#### Task P6-T01: Concrete AgentPool in `uaaf/execution/pool.py`

**Description:** Implement `AgentPool` — registry của `BaseAgent` instances với capability tags, bounded concurrency qua anyio Semaphore, và `fan_out` để dispatch N tasks song song. `dispatch()` dùng routing strategy thay vì hardcode "first registered". `fan_out()` có `on_error` mode để handle partial failure theo 2 semantics khác nhau.

**Interface target:**

```python
@dataclass
class AgentPool:
    max_concurrency: int = 8
    _agents: dict[str, BaseAgent]     # agent_id → agent (ordered — insertion order)
    _tags: dict[str, set[str]]        # agent_id → capability tags
    _rr_index: int = 0                # round_robin counter

    def register(self, agent: BaseAgent, tags: set[str] | None = None) -> None: ...
    def agents_with_tag(self, tag: str) -> list[BaseAgent]: ...
    def agent_ids(self) -> list[str]: ...

    async def dispatch(
        self,
        task: Task,
        context: ExecutionContext | None = None,
        strategy: Literal["round_robin", "random"] = "round_robin",
    ) -> AgentResult: ...
    # Routes using strategy. Raises ValueError if pool is empty.
    # round_robin: cycle through registered agents in insertion order.
    # random: pick a random agent from registry.

    async def dispatch_to(
        self, agent_id: str, task: Task, context: ExecutionContext
    ) -> AgentResult: ...
    # Routes to specific agent by id. Raises KeyError if not found.

    async def fan_out(
        self,
        tasks: list[Task],
        context: ExecutionContext,
        tag_filter: str | None = None,
        on_error: Literal["fail_fast", "collect"] = "fail_fast",
    ) -> list[AgentResult]: ...
    # Dispatch N tasks in parallel via anyio.create_task_group().
    # Bounded by Semaphore(max_concurrency).
    # Results ordered by input task order (index-stable, NOT completion order).
    # tag_filter: only dispatch to agents matching tag.
    #
    # on_error="fail_fast": anyio default — 1 task fail → cancel others, raise ExceptionGroup.
    # on_error="collect":   per-task CancelScope — collect ALL results + exceptions;
    #   failed tasks → AgentResult(success=False, metadata={"error": str(exc)}).
    #   Caller receives all N results, decides what to do with failures.
```

**Acceptance criteria:**
- [ ] `register()` + `agents_with_tag()` hoạt động đúng
- [ ] `dispatch(strategy="round_robin")` cycle qua agents theo insertion order; raise `ValueError` nếu pool empty
- [ ] `dispatch(strategy="random")` chọn ngẫu nhiên từ registry; raise `ValueError` nếu pool empty
- [ ] `dispatch_to()` route đúng agent; raise `KeyError` nếu agent_id không tồn tại
- [ ] `fan_out()` dùng `anyio.create_task_group()`, KHÔNG `asyncio.gather()`
- [ ] `fan_out()` kết quả giữ thứ tự input tasks (index-stable, `results[i] = ...` pattern)
- [ ] Bounded concurrency: `max_concurrency=2` với 5 tasks → không quá 2 agent chạy song song
- [ ] `fan_out(on_error="fail_fast")`: 1 task fail → `ExceptionGroup` propagate ra caller
- [ ] `fan_out(on_error="collect")`: 1 task fail → `AgentResult(success=False, metadata={"error": ...})`, các task khác tiếp tục và có kết quả đúng
- [ ] `fan_out()` với `tag_filter` chỉ dispatch đến agents matching tag
- [ ] AgentPool satisfy `IAgentPool` protocol (`isinstance(pool, IAgentPool)` = True)
- [ ] mypy clean, ruff clean

**Verification:**
- [ ] `pytest tests/unit/execution/test_pool.py` — 20+ tests pass
- [ ] `mypy uaaf/execution/pool.py` — 0 errors
- [ ] `ruff check uaaf/execution/pool.py` — 0 violations

**Dependencies:** None (IAgentPool Protocol đã có)

**Files:**
- `uaaf/execution/pool.py` (new — ~100 lines)
- `uaaf/execution/__init__.py` (update exports)
- `tests/unit/execution/test_pool.py` (new — ~140 lines)

**Estimated scope:** M (3 files)

---

#### Task P6-T02: Unit tests for AgentPool — edge cases + concurrency

**Description:** Test cases bổ sung cho partial failure modes, concurrency behaviour, routing correctness, và rate-limiter interaction — các paths mà T01 chưa cover đầy đủ.

**Acceptance criteria:**
- [ ] `fan_out(on_error="fail_fast")`: 1 task raise → `ExceptionGroup` propagate; các tasks đang chờ bị cancel
- [ ] `fan_out(on_error="collect")`: 1 task fail → `AgentResult(success=False)`; các task khác trả về kết quả đúng; kết quả đủ N phần tử
- [ ] Kết quả `fan_out(10 tasks, max_concurrency=3)` đúng thứ tự input (không phải completion order)
- [ ] `dispatch()` trên empty pool raise `ValueError` với message rõ ràng
- [ ] `dispatch_to("unknown")` raise `KeyError`
- [ ] `fan_out([], ...)` return `[]` không raise
- [ ] Round_robin: dispatch 5 lần trên pool 3 agents → cycle đúng (index 0, 1, 2, 0, 1)
- [ ] Rate-limiter saturation: `fan_out` với `max_concurrency=8` và worker apply `RateLimiter(3 rps)` → không deadlock; tasks complete trong `anyio.move_on_after(timeout)` fixture (graceful, không block mãi)

**Verification:**
- [ ] `pytest tests/unit/execution/test_pool.py -v` — tất cả pass
- [ ] Coverage `uaaf/execution/pool.py` ≥ 90%

**Dependencies:** T01

**Files:**
- `tests/unit/execution/test_pool.py` (extend T01 file)

**Estimated scope:** S (1 file)

---

### ✅ Checkpoint A — Sau T01 + T02

```
pytest tests/unit/execution/test_pool.py   → all pass
mypy uaaf/                                  → 0 errors
ruff check uaaf/ tests/                    → 0 violations
```

Review: AgentPool usable như building block trước khi tiếp tục.

---

### Phase B: ParallelFanoutStrategy

---

#### Task P6-T03: `ParallelFanoutStrategy` in `uaaf/cognitive/strategies/parallel.py`

**Description:** ICognitiveStrategy thứ 4 — nhận `StructuredIntent` với complexity HIGH, decompose thành N subtasks (deterministic hoặc via `ISubtaskBuilder`), dispatch qua `pool.fan_out(on_error="collect")`, aggregate kết quả thành `CognitiveResult`.

Dùng `on_error="collect"` thay vì `"fail_fast"` vì strategy cần aggregate partial results — 1 worker fail không nên cancel toàn bộ analysis.

**Interface target:**

```python
@runtime_checkable
class ISubtaskBuilder(Protocol):
    """Decomposes a StructuredIntent into a list of Tasks for parallel dispatch."""
    def build_subtasks(self, intent: StructuredIntent, context: ExecutionContext) -> list[Task]: ...

@dataclass
class EntitySubtaskBuilder:
    """Default ISubtaskBuilder: 1 task per entity in intent.entities."""
    def build_subtasks(self, intent: StructuredIntent, context: ExecutionContext) -> list[Task]:
        return [Task(task_id=f"subtask-{e}", payload={"entity": e}) for e in intent.entities]

@dataclass
class ParallelFanoutStrategy:
    strategy_id: str = "parallel_fanout"
    max_workers: int = 8
    subtask_builder: ISubtaskBuilder = field(default_factory=EntitySubtaskBuilder)

    def applicable(self, intent: StructuredIntent, context: ExecutionContext) -> bool:
        # True khi: complexity == HIGH AND len(intent.entities) > 1
        ...

    def estimate_cost(self, intent, context) -> CostEstimate: ...

    async def execute(
        self, intent, context, agent_pool, verifier
    ) -> CognitiveResult:
        # 1. subtask_builder.build_subtasks(intent) → list[Task]
        # 2. pool.fan_out(subtasks, context, on_error="collect") → list[AgentResult]
        # 3. Filter successful results; log failed ones
        # 4. aggregate successful outputs → combined_output str
        # 5. verifier.verify(combined_output, context)
        # 6. return CognitiveResult(output, confidence, strategy_id)
        ...
```

**Acceptance criteria:**
- [ ] `applicable()` True khi complexity=HIGH và entities > 1; False otherwise
- [ ] `execute()` gọi `pool.fan_out(on_error="collect")` (KHÔNG `"fail_fast"`)
- [ ] `execute()` aggregate tất cả `AgentResult.output` từ successful workers thành combined string
- [ ] `execute()` log/skip failed workers (không raise khi 1 worker fail)
- [ ] `execute()` gọi `verifier.verify()` trên combined output
- [ ] `CognitiveResult.strategy_id == "parallel_fanout"`
- [ ] `isinstance(strategy, ICognitiveStrategy)` = True
- [ ] Custom `ISubtaskBuilder` inject được qua constructor
- [ ] mypy clean

**Verification:**
- [ ] `pytest tests/unit/cognitive/test_parallel.py` — 12+ tests pass
- [ ] `pytest tests/contract/test_strategy_contract.py` — ParallelFanoutStrategy pass contract
- [ ] `mypy uaaf/cognitive/strategies/parallel.py` — 0 errors

**Dependencies:** T01 (dùng AgentPool.fan_out)

**Files:**
- `uaaf/cognitive/strategies/parallel.py` (new — ~90 lines, gồm `ISubtaskBuilder` Protocol + `EntitySubtaskBuilder` default impl + `ParallelFanoutStrategy`)
- `uaaf/cognitive/strategies/__init__.py` (update exports)
- `tests/unit/cognitive/test_parallel.py` (new — ~110 lines, test cả custom và default SubtaskBuilder, test partial failure aggregation)
- `tests/contract/test_strategy_contract.py` (add ParallelFanoutStrategy to parametrize)

**Estimated scope:** M (4 files)

---

### ✅ Checkpoint B — Sau T03

```
pytest tests/unit/cognitive/ tests/contract/test_strategy_contract.py  → all pass
pytest tests/                                                            → no regression (395+ pass)
mypy uaaf/                                                              → 0 errors
ruff check uaaf/ tests/                                                 → 0 violations
coverage uaaf/execution/pool.py                                         → ≥ 90%
coverage uaaf/cognitive/strategies/parallel.py                          → ≥ 85%
```

Human review trước khi tiếp tục Phase C.

---

### Phase C: Refactor + Housekeeping

*(Gộp Phase C + D từ plan gốc sau khi bỏ OrchestratorAgent)*

---

#### Task P6-T06: Update `examples/code_analysis` — replace `asyncio.gather` with `AgentPool`

**Description:** `CodebaseAnalysisOrchestrator` hiện dùng `asyncio.gather()` — vi phạm anyio rule của spec. Refactor để dùng `AgentPool.fan_out()`. `AgentFactory` vẫn giữ nhưng kết quả của nó được đưa vào `AgentPool.register()` thay vì gọi trực tiếp.

> **Follow-up note (không block Phase 6):** Workers hiện tại (`ClassAnalysisAgent`) extend `BaseAgent` trực tiếp. Sau khi LLMAgent plan hoàn thành, nên refactor workers sang `LLMAgent` để tận dụng built-in `react_loop` và `ToolRegistry`. Track là post-Phase-6 item.

**Acceptance criteria:**
- [ ] `asyncio.gather` bị xóa khỏi `examples/code_analysis/agents.py`
- [ ] `asyncio` module không còn được import trong file này
- [ ] `CodebaseAnalysisOrchestrator` dùng `AgentPool.fan_out()` thay thế
- [ ] Behaviour không thay đổi: N agents chạy song song, kết quả aggregate vào `CodebaseReport`
- [ ] Demo mode (FakeLLMProvider) vẫn hoạt động
- [ ] `mypy examples/` — 0 errors

**Verification:**
- [ ] `pytest tests/` — không có regression
- [ ] `grep -r "asyncio.gather" examples/` — không tìm thấy kết quả
- [ ] `grep -r "import asyncio" examples/code_analysis/agents.py` — không tìm thấy
- [ ] `python -c "from examples.code_analysis.agents import CodebaseAnalysisOrchestrator"` — import clean

**Dependencies:** T01

**Files:**
- `examples/code_analysis/agents.py` (modify — thay `asyncio.gather` section)

**Estimated scope:** S (1 file, surgical change)

---

#### Task P6-T07: Update `_testing/fakes.py` — add `fan_out` to `FakeAgentPool`

**Description:** `FakeAgentPool` chỉ có `dispatch()`. Cần thêm `fan_out(tasks, context, on_error="fail_fast")` để product test code dùng `FakeAgentPool` thay `AgentPool` khi test code sử dụng `fan_out`.

**Acceptance criteria:**
- [ ] `FakeAgentPool.fan_out(tasks, context, on_error="fail_fast")` trả về `list[AgentResult]` từ queue
- [ ] `on_error` param được nhận nhưng behavior trong fake là đơn giản: trả hết queue (không cancel)
- [ ] `fan_out` track `dispatch_count` (tất cả subtasks)
- [ ] `isinstance(FakeAgentPool(), IAgentPool)` = True vẫn giữ
- [ ] Backward compatible — existing tests không bị break

**Verification:**
- [ ] `pytest tests/unit/_testing/` — pass
- [ ] `mypy uaaf/_testing/fakes.py` — 0 errors

**Dependencies:** T01

**Files:**
- `uaaf/_testing/fakes.py` (modify — add `fan_out` method, ~15 lines)

**Estimated scope:** XS (1 file)

---

#### Task P6-T08: CHANGELOG + public API exports + project memory

**Description:** Housekeeping: CHANGELOG v0.1.0b6 entry, update `uaaf/__init__.py` exports cho `AgentPool` + `ParallelFanoutStrategy` + `ISubtaskBuilder`, update project memory.

**Acceptance criteria:**
- [ ] `CHANGELOG.md` có entry `v0.1.0b6` với list components mới
- [ ] `from uaaf import AgentPool` hoạt động
- [ ] `from uaaf.cognitive.strategies import ParallelFanoutStrategy, ISubtaskBuilder` hoạt động
- [ ] `from uaaf.execution import ToolRegistry, ITool` hoạt động (sau khi LLMAgent plan merge)
- [ ] Project memory updated: Phase 6 status

**Verification:**
- [ ] `python -c "from uaaf import AgentPool"` — no ImportError
- [ ] `python -c "from uaaf.cognitive.strategies import ParallelFanoutStrategy"` — no ImportError
- [ ] CI gate cuối: `ruff + mypy + pytest` — all green

**Dependencies:** T01–T07

**Files:**
- `CHANGELOG.md`
- `uaaf/__init__.py`
- project memory file

**Estimated scope:** XS (3 files)

---

### ✅ Final Checkpoint — Phase 6 Complete

```
ruff check uaaf/ tests/ examples/                      → 0 violations
mypy uaaf/ examples/                                   → 0 errors
pytest tests/ --cov=uaaf --cov-fail-under=88           → ≥ 395 tests pass, ≥ 88% coverage
grep -r "asyncio.gather" uaaf/                         → no results (spec compliance)
grep -r "asyncio.gather" examples/code_analysis/       → no results
python -c "from uaaf import AgentPool"                 → no ImportError
python -c "from uaaf.cognitive.strategies import ParallelFanoutStrategy"  → no ImportError
```

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| anyio Semaphore API khác asyncio.Semaphore | Med | Read anyio docs trước khi code; test concurrency bound explicitly |
| Result ordering với fan_out (race condition) | High | Dùng index-stable pattern: `results[i] = ...` trong task group, KHÔNG `results.append()` |
| `on_error="collect"` CancelScope leak nếu implement sai | High | Unit test explicit: verify all N results returned; verify failed task không block others |
| Rate-limiter saturation deadlock với high max_concurrency | Med | T02 test case dùng anyio timeout fixture; implement CancelScope per-task cho collect mode |
| IAgentPool Protocol mismatch sau khi thêm `fan_out` params | Low | `FakeAgentPool.fan_out` là extra method, không phải protocol requirement — OK |
| Coverage drop nếu `on_error` branches nhiều | Med | Test cả 2 modes (fail_fast + collect) với ít nhất 1 test per failure scenario |

---

## Resolved Decisions

- **SubtaskBuilder**: dùng `ISubtaskBuilder` Protocol (structural typing, testable, injectable) — không dùng bare callable.
- **Phase 7 scope**: `uaaf/workflow/` — WorkflowEngine + StateMachine + ICheckpointStore (batch mode, SIGKILL-safe resume). Implement sau khi Phase 6 CI gate green.
- **OrchestratorAgent — deferred (Fix #5)**: Expert review xác định nó duplicate với `ParallelFanoutStrategy`. Cả hai thực hiện cùng flow (decompose → fan_out → aggregate) mà không có use case framework cụ thể để justify 2 implementations. Option A được chọn: bỏ khỏi framework core. Nếu product cần supervisor pattern, viết ở `examples/` như `CodebaseAnalysisOrchestrator` hiện tại, hoặc xem xét lại khi có concrete use case đủ để abstract.
- **dispatch() routing (Fix #7)**: `"round_robin"` là default thay vì "first registered". Caller muốn exact routing dùng `dispatch_to(agent_id, ...)`.
- **fan_out partial failure (Fix #6)**: `"fail_fast"` là default (anyio semantic, all-or-nothing). `"collect"` mode cho use cases cần partial results (như `ParallelFanoutStrategy`).
- **Verifier là trách nhiệm của Strategy tier**: `AgentPool` và individual agents không chạy verifier. Verifier được gọi trong `ParallelFanoutStrategy.execute()` — không phải ở agent layer.
