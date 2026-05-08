# Workflow Engine & State Machine — Khái niệm và So sánh

## WorkflowEngine giải quyết bài toán gì?

5 AI agent pattern (DirectStrategy, ReAct, Parallelization, Orchestrator-Worker, Evaluator-Optimizer)
đều xử lý **một request trong vài giây đến vài phút**. Nếu process die → chạy lại từ đầu, không sao.

WorkflowEngine giải quyết **batch job chạy hàng giờ** cần fault-tolerant:

```
Code ingestion — codebase 50k dòng:
  PARSING          → parse 500 files                  (5 phút)
  ENHANCEMENT      → LLM phân tích 200 class          (40 phút)  ← crash ở đây?
  GOLD_DERIVATION  → tính metrics, build graph        (10 phút)
  DONE

Không crash: 55 phút tổng
Crash lúc class thứ 87 → resume từ class 87, không parse lại từ đầu
```

---

## Ba thành phần

```
WorkflowEngine              StateMachine                ICheckpointStore
────────────────────        ────────────────────────    ─────────────────────────
run(workflow, input)        execute(current_state)      save(id, state, data)
resume(workflow_id)  ──►    next_state()          ──►   load(id) → dict | None
                            on_error(state)
```

- **`StateMachine`**: định nghĩa graph trạng thái + transition rules. Mỗi state chạy qua `AgentPool`.
- **`ICheckpointStore`**: sau mỗi state thành công → save. Crash → load, tiếp tục từ điểm đó.
- **`WorkflowEngine`**: vòng lặp `execute → checkpoint → next_state` cho đến terminal state.

**Luồng thực thi:**
```
engine.run(workflow, input)
    │
    ├── SM: init state = PARSING
    ├── CP: load_or_create(workflow_id)
    │
    └── loop until terminal:
        ├── SM: execute(current_state) → AgentPool → LLM agents
        ├── CP: save(state, output)          ← SIGKILL-safe point
        └── SM: next_state()
```

---

## So sánh với AWS Step Functions

### Điểm giống nhau

| Concept | AWS Step Functions | UAAF WorkflowEngine |
|---|---|---|
| State machine | ✅ states + transitions | ✅ states + transitions |
| Checkpoint sau mỗi state | ✅ DynamoDB (managed) | ✅ `ICheckpointStore` (bạn chọn backend) |
| Resume sau crash | ✅ automatic | ✅ `engine.resume(workflow_id)` |
| Retry per state | ✅ built-in retry policy | ✅ exponential backoff |
| Parallel trong 1 state | ✅ `Map` state | ✅ `AgentPool.fan_out()` |

### Ba điểm khác biệt quan trọng

**1. Worker ở mỗi state là gì:**
```
Step Functions:  state → Lambda / ECS / SQS / bất kỳ AWS service
UAAF:            state → AgentPool → LLM agents

Step Functions orchestrate services.
UAAF orchestrate LLM reasoning.
```

**2. Distributed vs in-process:**
```
Step Functions:  managed service, chạy song song hàng triệu execution
UAAF:            embedded library, chạy trong process Python của bạn
```
Step Functions là infrastructure. UAAF WorkflowEngine là library.

**3. Cách define state:**
```json
// Step Functions — Amazon States Language (JSON/YAML)
{
  "States": {
    "Parsing": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:...:parser-fn",
      "Next": "Enhancement"
    },
    "Enhancement": {
      "Type": "Map",
      "Iterator": { "StartAt": "AnalyzeClass" },
      "Next": "Done"
    }
  }
}
```

```python
# UAAF — Python thuần, code-first
class IngestionWorkflow:
    states      = [PARSING, ENHANCEMENT, GOLD_DERIVATION, DONE, ERROR]
    initial     = PARSING
    terminal    = {DONE, ERROR}
    transitions = {
        PARSING:          ENHANCEMENT,
        ENHANCEMENT:      GOLD_DERIVATION,
        GOLD_DERIVATION:  DONE,
    }
```

### Bảng tổng hợp

```
                    Step Functions      UAAF WorkflowEngine     Temporal/Cadence
─────────────────── ──────────────────  ──────────────────────  ────────────────────
Worker              AWS services        LLM agents              Arbitrary code
Execution model     Distributed/managed In-process library      Distributed/managed
State definition    JSON (ASL)          Python code             Python/Go/Java code
Checkpoint storage  DynamoDB (managed)  ICheckpointStore (DIY)  Cassandra (managed)
Max duration        1 year              Hours                   Unlimited
Concurrent runs     Millions            Single-process limit    Millions
Scale-out           AWS manages         Deploy more workers     Temporal manages
Cost model          Per state transition Free (self-hosted)      Self-hosted or cloud
```

---

## Quan hệ với 5 pattern hiện có

WorkflowEngine **không thay thế** 5 pattern — nó là lớp bên trên:

```
WorkflowEngine
    │
    ├── State: PARSING
    │     └── AgentPool.dispatch(ParserAgent)           ← Pattern 3 (single dispatch)
    │
    ├── State: ENHANCEMENT
    │     └── AgentPool.fan_out(per-class tasks)        ← Pattern 3 (Parallelization)
    │         └── ClassAnalysisAgent → LLM              ← Pattern 1 (Prompt Chaining)
    │
    └── State: GOLD_DERIVATION
          └── EvaluatorOptimizerStrategy.execute()      ← Pattern 5
```

Mỗi state của workflow có thể dùng bất kỳ strategy nào trong 5 pattern.

---

## Use case cụ thể trong các ví dụ của UAAF

| Project | Workflow states | Lý do cần WorkflowEngine |
|---|---|---|
| **Code Analysis** | PARSING → ENHANCEMENT → GOLD_DERIVATION → REPORT | Job CI hàng đêm, 500+ files, cần resume nếu timeout |
| **Flashcard System** | SCHEDULE → REVIEW_BATCH → UPDATE_SM2 → RESCHEDULE | Spaced repetition chạy hàng ngày, nhiều user |
| **Stock Trading** | FETCH_DATA → BACKTEST → SIGNAL_GEN → EXECUTE | Chạy trước giờ mở cửa, không được bỏ lỡ state nào |

---

## Thiết kế `ICheckpointStore` — Protocol pattern

Framework chỉ define interface. Project tự chọn backend:

```python
# uaaf/workflow/checkpoint.py
@runtime_checkable
class ICheckpointStore(Protocol):
    async def save(self, workflow_id: str, state: str, data: dict) -> None: ...
    async def load(self, workflow_id: str) -> dict | None: ...
    async def delete(self, workflow_id: str) -> None: ...

# Built-in: dev/test
class InMemoryCheckpointStore:
    ...

# Project tự implement theo nhu cầu:
# class RedisCheckpointStore(ICheckpointStore): ...
# class PostgresCheckpointStore(ICheckpointStore): ...
# class S3CheckpointStore(ICheckpointStore): ...
```

Nếu sau này cần scale distributed → replace `InMemoryCheckpointStore` bằng `RedisCheckpointStore`
hoặc migrate sang Temporal — business logic không thay đổi vì `ICheckpointStore` là Protocol.

---

## Khi nào dùng WorkflowEngine vs pattern thông thường?

```
Request đến
    │
    ├── Xử lý xong trong < 5 phút?
    │   └── → Dùng 5 pattern (DirectStrategy, ReAct, v.v.)
    │
    ├── Job batch, chạy hàng giờ, cần fault-tolerance?
    │   └── → UAAF WorkflowEngine (Phase 7)
    │
    └── Hàng nghìn concurrent workflow, cần distributed?
        └── → Temporal / Prefect / AWS Step Functions
              (UAAF WorkflowEngine là stepping stone, ICheckpointStore là exit ramp)
```
