# Implementation Plan: Phase 6 — Multi-Agent Orchestration

## Overview

Nâng multi-agent từ "DIY ở tầng application" lên **framework-level feature**. Hiện tại `IAgentPool` Protocol đã có nhưng không có concrete implementation; `examples/code_analysis` dùng `asyncio.gather()` trực tiếp — vi phạm spec anyio. Phase 6 xây 3 component chính: **AgentPool** (registry + routing + bounded concurrency), **ParallelFanoutStrategy** (ICognitiveStrategy thứ 4), và **OrchestratorAgent** (supervisor-worker pattern qua BaseAgent).

Scope KHÔNG bao gồm: `uaaf/workflow/` (WorkflowEngine + StateMachine + Checkpoint) — để lại Phase 7.

**CI gate đầu vào (Phase 5):** ruff ✓, mypy ✓, 383 tests pass, 91.48% coverage.

---

## Architecture Decisions

- **anyio task group, KHÔNG asyncio.gather** — spec tại §5 cấm `import asyncio` trong `uaaf/`; `anyio.create_task_group()` là primitive đúng.
- **AgentPool là dataclass, không phải singleton** — caller tự quản lý lifecycle; testable, injectable.
- **`dispatch(task, context)` — context là required param** — `IAgentPool` Protocol chỉ định nghĩa `dispatch(task)` minimal; concrete AgentPool mở rộng với `context` qua default arg để satisfy protocol và pass context xuống `BaseAgent.execute()`.
- **`fan_out` là method riêng, không phải overload của `dispatch`** — signature rõ ràng, tránh ambiguity.
- **OrchestratorAgent extends BaseAgent** — cross-cutting (cost/trace/audit/rate-limit) được inject tự động; chỉ cần implement `_execute()`.
- **ParallelFanoutStrategy là ICognitiveStrategy thứ 4** — cùng contract với Direct/ReAct/EvaluatorOptimizer; StrategySelector có thể chọn nó khi complexity=HIGH.

---

## Dependency Graph

```
IAgentPool Protocol (đã có)
    │
    └── AgentPool (T01) ← foundation của mọi thứ
            │
            ├── ParallelFanoutStrategy (T02) — dùng pool.fan_out()
            │       │
            │       └── Contract test update (T03)
            │
            ├── OrchestratorAgent (T04) — dùng pool.fan_out() + pool.dispatch()
            │       │
            │       └── Integration smoke test (T05)
            │
            └── examples/code_analysis refactor (T06) — replace asyncio.gather
```

Build từ bottom: T01 → T02 → T03 → checkpoint → T04 → T05 → checkpoint → T06 → T07 → T08.

---

## Task List

### Phase A: AgentPool Foundation

---

#### Task P6-T01: Concrete AgentPool in `uaaf/execution/pool.py`

**Description:** Implement `AgentPool` — registry của `BaseAgent` instances với capability tags, bounded concurrency qua anyio Semaphore, và `fan_out` để dispatch N tasks song song.

**Interface target:**

```python
@dataclass
class AgentPool:
    max_concurrency: int = 8
    _agents: dict[str, BaseAgent]     # agent_id → agent
    _tags: dict[str, set[str]]        # agent_id → capability tags

    def register(self, agent: BaseAgent, tags: set[str] | None = None) -> None: ...
    def agents_with_tag(self, tag: str) -> list[BaseAgent]: ...
    def agent_ids(self) -> list[str]: ...

    async def dispatch(
        self, task: Task, context: ExecutionContext | None = None
    ) -> AgentResult: ...
    # Routes to first registered agent. Raises ValueError if pool is empty.

    async def dispatch_to(
        self, agent_id: str, task: Task, context: ExecutionContext
    ) -> AgentResult: ...
    # Routes to specific agent by id. Raises KeyError if not found.

    async def fan_out(
        self,
        tasks: list[Task],
        context: ExecutionContext,
        tag_filter: str | None = None,
    ) -> list[AgentResult]: ...
    # Dispatch N tasks in parallel via anyio.create_task_group().
    # Bounded by Semaphore(max_concurrency).
    # Results ordered by input task order (not completion order).
    # tag_filter: only dispatch to agents matching tag.
```

**Acceptance criteria:**
- [ ] `register()` + `agents_with_tag()` hoạt động đúng
- [ ] `dispatch()` route đến agent đầu tiên trong registry; raise `ValueError` nếu pool empty
- [ ] `dispatch_to()` route đúng agent; raise `KeyError` nếu agent_id không tồn tại
- [ ] `fan_out()` dùng `anyio.create_task_group()`, KHÔNG `asyncio.gather()`
- [ ] `fan_out()` kết quả giữ thứ tự input tasks (index-stable)
- [ ] Bounded concurrency: `max_concurrency=2` với 5 tasks → không quá 2 agent chạy song song
- [ ] `fan_out()` với `tag_filter` chỉ dispatch đến agents matching tag
- [ ] AgentPool satisfy `IAgentPool` protocol (`isinstance(pool, IAgentPool)` = True)
- [ ] mypy clean, ruff clean

**Verification:**
- [ ] `pytest tests/unit/execution/test_pool.py` — 18+ tests pass
- [ ] `mypy uaaf/execution/pool.py` — 0 errors
- [ ] `ruff check uaaf/execution/pool.py` — 0 violations

**Dependencies:** None (IAgentPool Protocol đã có)

**Files:**
- `uaaf/execution/pool.py` (new — ~80 lines)
- `uaaf/execution/__init__.py` (update exports)
- `tests/unit/execution/test_pool.py` (new — ~120 lines)

**Estimated scope:** M (3 files)

---

#### Task P6-T02: Unit tests for AgentPool — edge cases + concurrency

**Description:** Test cases bổ sung cho concurrency behaviour và error paths mà T01 chưa cover: exception propagation từ worker agent, empty pool, tag mismatch, result ordering với N > max_concurrency.

**Acceptance criteria:**
- [ ] Exception trong 1 worker propagate ra `fan_out()` caller (không bị nuốt)
- [ ] Kết quả `fan_out(10 tasks, max_concurrency=3)` đúng thứ tự
- [ ] `dispatch()` trên empty pool raise `ValueError` với message rõ ràng
- [ ] `dispatch_to("unknown")` raise `KeyError`
- [ ] `fan_out([], ...)` return `[]` không raise

**Verification:**
- [ ] `pytest tests/unit/execution/test_pool.py -v` — tất cả pass
- [ ] Coverage `uaaf/execution/pool.py` ≥ 90%

**Dependencies:** T01

**Files:**
- `tests/unit/execution/test_pool.py` (extend T01 file)

**Estimated scope:** S (1 file)

---

### Checkpoint A — Sau T01 + T02

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

**Description:** ICognitiveStrategy thứ 4 — nhận `StructuredIntent` với complexity HIGH, decompose thành N subtasks (deterministic hoặc LLM-assisted), dispatch qua `pool.fan_out()`, aggregate kết quả thành `CognitiveResult`.

**Interface target:**

```python
@runtime_checkable
class ISubtaskBuilder(Protocol):
    """Decomposes a StructuredIntent into a list of Tasks for parallel dispatch."""
    def build_subtasks(self, intent: StructuredIntent, context: ExecutionContext) -> list[Task]: ...

@dataclass
class ParallelFanoutStrategy:
    strategy_id: str = "parallel_fanout"
    max_workers: int = 8
    subtask_builder: ISubtaskBuilder | None = None
    # Default when None: 1 task per entity trong intent.entities

    def applicable(self, intent: StructuredIntent, context: ExecutionContext) -> bool:
        # True khi: complexity == HIGH AND len(intent.entities) > 1
        ...

    def estimate_cost(self, intent, context) -> CostEstimate: ...

    async def execute(
        self, intent, context, agent_pool, verifier
    ) -> CognitiveResult:
        # 1. build_subtasks(intent) → list[Task]
        # 2. pool.fan_out(subtasks, context) → list[AgentResult]
        # 3. aggregate outputs → combined_output str
        # 4. verifier.verify(combined_output, context)
        # 5. return CognitiveResult(output, confidence, strategy_id)
        ...
```

**Acceptance criteria:**
- [ ] `applicable()` True khi complexity=HIGH và entities > 1; False otherwise
- [ ] `execute()` gọi `pool.fan_out()` (không gọi `dispatch()` riêng lẻ)
- [ ] `execute()` aggregate tất cả AgentResult.output thành combined string
- [ ] `execute()` gọi `verifier.verify()` trên combined output
- [ ] `CognitiveResult.strategy_id == "parallel_fanout"`
- [ ] `isinstance(strategy, ICognitiveStrategy)` = True
- [ ] mypy clean

**Verification:**
- [ ] `pytest tests/unit/cognitive/test_parallel.py` — 12+ tests pass
- [ ] `pytest tests/contract/test_strategy_contract.py` — ParallelFanoutStrategy pass contract
- [ ] `mypy uaaf/cognitive/strategies/parallel.py` — 0 errors

**Dependencies:** T01 (dùng AgentPool.fan_out)

**Files:**
- `uaaf/cognitive/strategies/parallel.py` (new — ~85 lines, gồm `ISubtaskBuilder` Protocol + `EntitySubtaskBuilder` default impl)
- `uaaf/cognitive/strategies/__init__.py` (update exports)
- `tests/unit/cognitive/test_parallel.py` (new — ~110 lines, test cả custom và default SubtaskBuilder)
- `tests/contract/test_strategy_contract.py` (add ParallelFanoutStrategy to parametrize)

**Estimated scope:** M (4 files)

---

### Checkpoint B — Sau T03

```
pytest tests/unit/cognitive/ tests/contract/test_strategy_contract.py  → all pass
pytest tests/                                                            → no regression (383+ pass)
mypy uaaf/                                                              → 0 errors
```

---

### Phase C: OrchestratorAgent

---

#### Task P6-T04: `OrchestratorAgent` in `uaaf/execution/orchestrator.py`

**Description:** Supervisor agent — extends `BaseAgent` (cross-cutting gratis), có `worker_pool: AgentPool`. `_execute()` dùng LLM để decompose task thành subtasks, dispatch qua `worker_pool.fan_out()`, sau đó dùng LLM lần 2 để synthesize final answer từ worker outputs.

**Interface target:**

```python
@dataclass
class OrchestratorAgent(BaseAgent):
    llm: ILLMProvider
    worker_pool: AgentPool
    decompose_prompt: str = DEFAULT_DECOMPOSE_PROMPT
    synthesize_prompt: str = DEFAULT_SYNTHESIZE_PROMPT
    max_workers: int = 8

    async def _execute(self, task: Task, context: ExecutionContext) -> AgentResult:
        # Round 1: LLM decomposes task → list[SubtaskSpec]
        # Build list[Task] từ SubtaskSpec
        # fan_out(subtasks, context) → list[AgentResult]
        # Round 2: LLM synthesizes worker outputs → final answer
        # Return AgentResult(task_id, output=final_answer, cost=total_cost)
        ...
```

**Acceptance criteria:**
- [ ] `OrchestratorAgent` extends `BaseAgent` — cross-cutting auto-injected
- [ ] `_execute()` gọi LLM 2 lần: decompose + synthesize
- [ ] `_execute()` gọi `worker_pool.fan_out()` — không dispatch sequential
- [ ] Cost là tổng: orchestrator LLM cost + tất cả worker costs
- [ ] Nếu worker_pool rỗng, raise `ValueError` rõ ràng trước khi dispatch
- [ ] `FakeLLMProvider` đủ để test (không cần real API)
- [ ] mypy clean

**Verification:**
- [ ] `pytest tests/unit/execution/test_orchestrator.py` — 12+ tests pass
- [ ] `mypy uaaf/execution/orchestrator.py` — 0 errors

**Dependencies:** T01 (AgentPool), T02

**Files:**
- `uaaf/execution/orchestrator.py` (new — ~100 lines)
- `uaaf/execution/__init__.py` (update exports)
- `tests/unit/execution/test_orchestrator.py` (new — ~120 lines)

**Estimated scope:** M (3 files)

---

#### Task P6-T05: Integration smoke test — end-to-end multi-agent flow

**Description:** Smoke test kiểm tra full path: OrchestratorAgent → AgentPool.fan_out → 3 FakeWorkerAgents chạy song song → cost aggregation → kết quả trả về đúng.

**Acceptance criteria:**
- [ ] OrchestratorAgent với `worker_pool` có 3 workers → trả về AgentResult.success = True
- [ ] Total cost = orchestrator cost + sum(worker costs)
- [ ] Kết quả đúng thứ tự (worker-0, worker-1, worker-2)
- [ ] Test chạy không cần real LLM (dùng FakeLLMProvider + FakeAgentPool pattern)
- [ ] Test không flaky (không race condition)

**Verification:**
- [ ] `pytest tests/integration/test_phase6_smoke.py` — pass
- [ ] `pytest tests/` — tất cả existing tests vẫn pass (no regression)

**Dependencies:** T04

**Files:**
- `tests/integration/test_phase6_smoke.py` (new — ~80 lines)

**Estimated scope:** S (1 file)

---

### Checkpoint C — Sau T04 + T05

```
pytest tests/                               → 420+ tests pass, 0 failed
mypy uaaf/                                  → 0 errors (all new files)
ruff check uaaf/ tests/                    → 0 violations
coverage uaaf/execution/pool.py            → ≥ 90%
coverage uaaf/execution/orchestrator.py    → ≥ 85%
coverage uaaf/cognitive/strategies/        → ≥ 85%
```

Human review trước khi tiếp tục Phase D.

---

### Phase D: Refactor Examples + Housekeeping

---

#### Task P6-T06: Update `examples/code_analysis` — replace `asyncio.gather` with `AgentPool`

**Description:** `CodebaseAnalysisOrchestrator` hiện dùng `asyncio.gather()` — vi phạm anyio rule của spec. Refactor để dùng `AgentPool.fan_out()`. `AgentFactory` vẫn giữ nhưng kết quả của nó được đưa vào `AgentPool.register()` thay vì gọi trực tiếp.

**Acceptance criteria:**
- [ ] `asyncio.gather` bị xóa khỏi `examples/code_analysis/agents.py`
- [ ] `CodebaseAnalysisOrchestrator` dùng `AgentPool.fan_out()` thay thế
- [ ] Behaviour không thay đổi: N agents chạy song song, kết quả aggregate vào `CodebaseReport`
- [ ] Demo mode (FakeLLMProvider) vẫn hoạt động
- [ ] `mypy examples/` — 0 errors

**Verification:**
- [ ] `pytest tests/` — không có regression
- [ ] `grep -r "asyncio.gather" examples/` — không tìm thấy kết quả
- [ ] `python -c "from examples.code_analysis.agents import CodebaseAnalysisOrchestrator"` — import clean

**Dependencies:** T01

**Files:**
- `examples/code_analysis/agents.py` (modify — thay `asyncio.gather` section)

**Estimated scope:** S (1 file, surgical change)

---

#### Task P6-T07: Update `_testing/fakes.py` — add `fan_out` to `FakeAgentPool`

**Description:** `FakeAgentPool` chỉ có `dispatch()`. Cần thêm `fan_out(tasks, context)` để product test code dùng `FakeAgentPool` thay `AgentPool` khi test OrchestratorAgent.

**Acceptance criteria:**
- [ ] `FakeAgentPool.fan_out(tasks, context)` trả về `list[AgentResult]` từ queue
- [ ] `fan_out` track dispatch_count (tất cả subtasks)
- [ ] `isinstance(FakeAgentPool(), IAgentPool)` = True vẫn giữ
- [ ] Backward compatible — existing tests không bị break

**Verification:**
- [ ] `pytest tests/unit/_testing/` — pass
- [ ] `mypy uaaf/_testing/fakes.py` — 0 errors

**Dependencies:** T01

**Files:**
- `uaaf/_testing/fakes.py` (modify — add `fan_out` method)

**Estimated scope:** XS (1 file, ~15 lines)

---

#### Task P6-T08: CHANGELOG + public API exports + project memory

**Description:** Housekeeping: CHANGELOG v0.1.0b6 entry, update `uaaf/__init__.py` exports cho `AgentPool` + `OrchestratorAgent`, update project memory.

**Acceptance criteria:**
- [ ] `CHANGELOG.md` có entry `v0.1.0b6` với list components mới
- [ ] `from uaaf import AgentPool, OrchestratorAgent` hoạt động
- [ ] `from uaaf.cognitive.strategies import ParallelFanoutStrategy` hoạt động
- [ ] Project memory updated: Phase 6 status

**Verification:**
- [ ] `python -c "from uaaf import AgentPool, OrchestratorAgent"` — no ImportError
- [ ] CI gate cuối: `ruff + mypy + pytest` — all green

**Dependencies:** T01–T07

**Files:**
- `CHANGELOG.md`
- `uaaf/__init__.py`
- project memory file

**Estimated scope:** XS (3 files)

---

### Final Checkpoint — Phase 6 Complete

```
ruff check uaaf/ tests/ examples/          → 0 violations
mypy uaaf/ examples/                       → 0 errors
pytest tests/ --cov=uaaf --cov-fail-under=88
                                           → ≥ 420 tests pass, ≥ 88% coverage
grep -r "asyncio.gather" uaaf/             → no results (spec compliance)
python -c "from uaaf import AgentPool, OrchestratorAgent"
                                           → no ImportError
```

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| anyio Semaphore API khác asyncio.Semaphore | Med | Read anyio docs trước khi code; test concurrency bound explicitly |
| Result ordering với fan_out (race condition) | High | Dùng index-stable pattern: `results[i] = ...` trong task group, KHÔNG `results.append()` |
| OrchestratorAgent cost tổng sai (double-count) | Med | Unit test kiểm tra cost = orchestrator LLM + sum(workers), không phải 2× |
| IAgentPool Protocol mismatch sau khi thêm `fan_out` | Low | `FakeAgentPool.fan_out` là extra method, không phải protocol requirement — OK |
| Coverage drop nếu OrchestratorAgent branch nhiều | Med | Test cả path: empty pool, LLM decompose fail, worker fail |

## Resolved Decisions

- **SubtaskBuilder**: dùng `ISubtaskBuilder` Protocol (structural typing, testable, injectable) — không dùng bare callable.
- **Phase 7 scope**: `uaaf/workflow/` — WorkflowEngine + StateMachine + ICheckpointStore (batch mode, SIGKILL-safe resume). Implement sau khi Phase 6 CI gate green.
