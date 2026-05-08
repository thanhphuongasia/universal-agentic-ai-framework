# Pattern 3: Parallelization — `AgentPool.fan_out()`

## Pattern là gì?

Parallelization thực thi đồng thời N task độc lập, giảm thời gian từ `O(n)` xuống gần `O(1)`.
`AgentPool.fan_out()` là primitive cấp thấp: phân phối tasks tới agents theo round-robin,
chạy qua `anyio` task group với `Semaphore(max_concurrency)`, trả kết quả **giữ nguyên thứ tự input** (index-stable).

Hai chế độ lỗi:
- `on_error="fail_fast"`: 1 task lỗi → hủy tất cả, raise `ExceptionGroup`.
- `on_error="collect"`: tất cả chạy đến hết; lỗi thành `AgentResult(success=False)`.

## Khi nào nên dùng?

- N task **hoàn toàn độc lập** (không task nào cần kết quả task khác).
- Cần kiểm soát concurrency để tránh rate-limit (`max_concurrency`).
- Cần kết quả theo đúng thứ tự input.

**Pattern này khác Pattern 4**: fan_out là primitive thuần túy — không phân rã, không tổng hợp. Pattern 4 (Orchestrator-Worker) dùng fan_out ở tầng trên và thêm decompose + aggregate.

## UAAF triển khai như thế nào?

```
fan_out([t0, t1, t2, t3], on_error="collect")
    │
    ├── results = [None, None, None, None]   ← index-stable
    ├── semaphore = anyio.Semaphore(max_concurrency)
    └── anyio task group:
        ├── _run_collect(agent[0], t0, results, idx=0, sem)
        ├── _run_collect(agent[1], t1, results, idx=1, sem)
        ├── _run_collect(agent[0], t2, results, idx=2, sem)  ← round-robin
        └── _run_collect(agent[1], t3, results, idx=3, sem)
```

## Ví dụ: Code Analysis — Scan nhiều file Python đồng thời

Khi phân tích codebase, mỗi file là một task độc lập — không file nào cần kết quả của file khác.
Fan_out giảm thời gian từ `O(n files × latency)` xuống `O(latency)` (với đủ concurrency).

```python
import anyio
from uaaf import (
    AgentPool, BaseAgent, AgentResult, Task,
    ExecutionContext, ContextScope, Cost,
)


class FileAnalysisAgent(BaseAgent):
    """Phân tích 1 file Python: đếm class, method, docstring coverage."""

    async def _execute(self, task: Task, ctx: ExecutionContext) -> AgentResult:
        filepath = task.payload["filepath"]
        # Thực tế: đọc file và gọi LLM phân tích
        # Ở đây giả lập kết quả
        report = {
            "file": filepath,
            "classes": 3,
            "methods": 12,
            "docstring_coverage": 0.75,
            "complexity": "MEDIUM",
        }
        import json
        return AgentResult(
            task_id=task.task_id,
            output=json.dumps(report),
            cost=Cost.zero(),
        )


async def main():
    from uaaf.observability.audit import AuditLogger
    from uaaf.observability.cost import CostPolicy, CostTracker
    from uaaf.observability.rate_limit import RateLimiter, RatePolicy
    from uaaf.observability.tracer import Tracer
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    def make_agent(name: str) -> FileAnalysisAgent:
        return FileAnalysisAgent(
            agent_id=name,
            cost_tracker=CostTracker(CostPolicy()),
            tracer=Tracer("demo", InMemorySpanExporter()),
            audit_logger=AuditLogger(),
            rate_limiter=RateLimiter(RatePolicy(rps=100.0, burst=20)),
        )

    # 3 worker agents — fan_out phân phối round-robin
    pool = AgentPool(max_concurrency=3)
    pool.register(make_agent("analyzer-0"))
    pool.register(make_agent("analyzer-1"))
    pool.register(make_agent("analyzer-2"))

    # 8 file cần phân tích — hoàn toàn độc lập nhau
    files = [
        "uaaf/execution/agent.py",
        "uaaf/execution/pool.py",
        "uaaf/providers/router.py",
        "uaaf/providers/circuit_breaker.py",
        "uaaf/cognitive/strategies/react.py",
        "uaaf/cognitive/strategies/parallel.py",
        "uaaf/cognitive/verifiers/pipeline.py",
        "uaaf/observability/cost.py",
    ]
    tasks = [
        Task(task_id=f"file-{i}", payload={"filepath": f})
        for i, f in enumerate(files)
    ]

    ctx = ExecutionContext(
        scope=ContextScope(user_id="ci-bot", session_id="scan-001", domain="code_analysis"),
        correlation_id="batch-file-scan",
    )

    # --- collect mode: một file lỗi không dừng cả batch ---
    results = await pool.fan_out(tasks, ctx, on_error="collect")

    import json
    successes = [r for r in results if r.success]
    failures  = [r for r in results if not r.success]

    print(f"Phân tích thành công: {len(successes)}/{len(tasks)} file")
    for r in successes:
        data = json.loads(r.output)
        print(f"  {data['file']}: {data['classes']} class, "
              f"docstring {data['docstring_coverage']:.0%}")

    if failures:
        for r in failures:
            print(f"  FAIL {r.task_id}: {r.metadata.get('error', '?')}")

    # --- fail_fast mode: dùng khi batch là atomic (tất cả phải thành công) ---
    try:
        results = await pool.fan_out(tasks, ctx, on_error="fail_fast")
    except ExceptionGroup as eg:
        print(f"Batch thất bại: {len(eg.exceptions)} lỗi")

    # --- tag_filter: chỉ dùng agent chuyên biệt ---
    pool.register(make_agent("async-specialist"), tags={"async"})
    async_tasks = [Task(task_id="async-0", payload={"filepath": "uaaf/execution/pool.py"})]
    results = await pool.fan_out(async_tasks, ctx, tag_filter="async", on_error="collect")


anyio.run(main)
```

**Use case khác phù hợp Pattern 3:**
- **Stock Trading**: Lấy giá realtime cho 50 ticker cùng lúc — mỗi ticker là 1 API call độc lập
- **Flashcard System**: Generate embedding cho 200 flashcard để index vào vector store — mỗi card độc lập
- **Todo Pro**: Gửi reminder notification tới nhiều user — mỗi notification độc lập

## Interface chính

```python
@dataclass
class AgentPool:
    max_concurrency: int = 8  # số task chạy song song tối đa

    def register(self, agent: BaseAgent, tags: set[str] | None = None) -> None: ...

    async def fan_out(
        self,
        tasks: list[Task],
        context: ExecutionContext,
        tag_filter: str | None = None,
        on_error: Literal["fail_fast", "collect"] = "fail_fast",
    ) -> list[AgentResult]:
        # results[i] luôn tương ứng tasks[i] (index-stable)
        # on_error="collect": AgentResult(success=False) cho task lỗi
        ...

    async def dispatch(
        self, task: Task,
        context: ExecutionContext | None = None,
        strategy: Literal["round_robin", "random"] = "round_robin",
    ) -> AgentResult: ...
```

## Lưu ý quan trọng

- **Index-stable**: `results[i]` ↔ `tasks[i]` bất kể thứ tự hoàn thành.
- **`on_error="collect"`** cho production khi partial failure chấp nhận được — kiểm tra `result.success` và `result.metadata["error"]`.
- **`max_concurrency`** là giới hạn đồng thời, không phải số task — `fan_out(1000 tasks, max_concurrency=8)` hợp lệ.
- Pool rỗng hoặc không có agent nào match `tag_filter` → raise `ValueError` ngay lập tức.
