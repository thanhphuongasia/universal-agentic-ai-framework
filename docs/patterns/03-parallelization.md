# Pattern 3: Parallelization — `AgentPool.fan_out()`

## Pattern là gì?

Parallelization là kỹ thuật thực thi đồng thời nhiều task độc lập thay vì tuần tự, giúp giảm
tổng thời gian xử lý từ `O(n)` xuống gần `O(1)` (bị giới hạn bởi `max_concurrency`).
Trong UAAF, `AgentPool.fan_out()` là primitive cấp thấp cho pattern này: nó nhận một danh sách
`Task`, phân phối chúng tới các agent theo round-robin, chạy đồng thời qua `anyio` task group
với `Semaphore` giới hạn số worker, và trả về kết quả **giữ nguyên thứ tự input** (index-stable).

Có hai chế độ xử lý lỗi:
- `on_error="fail_fast"`: một task lỗi → hủy tất cả task còn lại, raise `ExceptionGroup`.
- `on_error="collect"`: mọi task đều chạy đến hết; lỗi được lưu thành `AgentResult(success=False)`.

## Khi nào nên dùng?

- Có N task hoàn toàn độc lập nhau (không task nào cần kết quả của task khác).
- Muốn kiểm soát tối đa concurrency để tránh rate-limit LLM (`max_concurrency`).
- Cần xử lý partial failure: dùng `on_error="collect"` để lấy kết quả thành công và ghi nhận lỗi riêng.
- Cần kết quả theo đúng thứ tự input (không muốn sort lại sau khi chạy song song).
- Ví dụ: embedding nhiều đoạn văn bản, gọi LLM cho nhiều document độc lập, xử lý batch request.

## UAAF triển khai như thế nào?

| Thành phần | Vị trí |
|-----------|--------|
| `AgentPool` | `uaaf/execution/pool.py` |
| `AgentPool.fan_out()` | `uaaf/execution/pool.py` |
| `BaseAgent` | `uaaf/execution/agent.py` |
| `AgentResult` | `uaaf/execution/agent.py` |
| `Task` | `uaaf/execution/agent.py` |

**Cơ chế bên trong `fan_out()`:**

```
fan_out(tasks=[t0, t1, t2, t3], context, on_error="collect")
    │
    ├── results = [None, None, None, None]  ← pre-allocated, index-stable
    ├── semaphore = anyio.Semaphore(max_concurrency)
    │
    └── anyio task group:
        ├── _run_collect(agent[0%n], t0, results, idx=0, semaphore)
        ├── _run_collect(agent[1%n], t1, results, idx=1, semaphore)
        ├── _run_collect(agent[2%n], t2, results, idx=2, semaphore)
        └── _run_collect(agent[3%n], t3, results, idx=3, semaphore)
    │
    └── return [results[0], results[1], results[2], results[3]]
```

Agent được phân phối theo `i % len(candidates)` — round-robin trên danh sách candidates.
Nếu có `tag_filter`, chỉ agents có tag đó mới được chọn.

## Ví dụ code

```python
import anyio
from uaaf.execution.pool import AgentPool
from uaaf.execution.agent import BaseAgent, AgentResult, Task
from uaaf.runtime.context import ExecutionContext, ContextScope
from uaaf.observability.cost import Cost


class SummaryAgent(BaseAgent):
    """Agent tóm tắt một đoạn văn bản."""
    agent_id = "summarizer"

    async def execute(self, task: Task, context: ExecutionContext) -> AgentResult:
        doc = task.payload.get("document", "")
        summary = f"Tóm tắt: {doc[:50]}..."   # giả lập LLM
        return AgentResult(task_id=task.task_id, output=summary, cost=Cost.zero())


async def main():
    pool = AgentPool(max_concurrency=3)  # tối đa 3 task chạy cùng lúc
    pool.register(SummaryAgent())

    # 4 document cần xử lý độc lập nhau
    documents = [
        "Tài liệu A: Hệ thống phân tán là ...",
        "Tài liệu B: Machine learning cho phép ...",
        "Tài liệu C: Kiến trúc microservices ...",
        "Tài liệu D: DevOps và CI/CD ...",
    ]
    tasks = [
        Task(task_id=f"doc-{i}", payload={"document": doc})
        for i, doc in enumerate(documents)
    ]

    context = ExecutionContext(
        scope=ContextScope(user_id="u1", session_id="s1", domain="docs"),
        correlation_id="fanout-demo",
    )

    # --- fail_fast: một lỗi hủy tất cả ---
    results = await pool.fan_out(tasks, context, on_error="fail_fast")
    for task, result in zip(tasks, results):
        print(f"{task.task_id}: {result.output}")

    # --- collect: lấy kết quả dù có lỗi ---
    results = await pool.fan_out(tasks, context, on_error="collect")
    successes = [r for r in results if r.success]
    failures  = [r for r in results if not r.success]
    print(f"Thành công: {len(successes)}, Lỗi: {len(failures)}")

    # --- tag_filter: chỉ dùng agent có tag "fast" ---
    fast_agent = SummaryAgent()
    fast_agent.agent_id = "summarizer-fast"
    pool.register(fast_agent, tags={"fast"})

    results = await pool.fan_out(tasks[:2], context, tag_filter="fast", on_error="collect")
    print(f"Kết quả qua tag 'fast': {len(results)}")


anyio.run(main)
```

## Interface chính

```python
@dataclass
class AgentPool:
    max_concurrency: int = 8  # giới hạn số task chạy song song qua Semaphore

    def register(
        self,
        agent: BaseAgent,
        tags: set[str] | None = None,
    ) -> None:
        # Đăng ký agent vào pool; re-register cùng agent_id sẽ ghi đè
        ...

    async def dispatch(
        self,
        task: Task,
        context: ExecutionContext | None = None,
        strategy: Literal["round_robin", "random"] = "round_robin",
    ) -> AgentResult:
        # Gửi 1 task tới agent được chọn theo strategy
        ...

    async def fan_out(
        self,
        tasks: list[Task],
        context: ExecutionContext,
        tag_filter: str | None = None,       # lọc theo tag nếu cần
        on_error: Literal["fail_fast", "collect"] = "fail_fast",
    ) -> list[AgentResult]:
        # Kết quả index-stable: results[i] tương ứng tasks[i]
        # on_error="fail_fast": ExceptionGroup nếu bất kỳ task nào lỗi
        # on_error="collect":   AgentResult(success=False) cho task lỗi
        ...

    def agents_with_tag(self, tag: str) -> list[BaseAgent]: ...
    def agent_ids(self) -> list[str]: ...
```

## Lưu ý quan trọng

- **Index-stable**: `results[i]` luôn tương ứng `tasks[i]`, bất kể thứ tự hoàn thành.
  Không cần sort hay map lại.
- **`on_error="collect"`** phù hợp cho production khi partial failure chấp nhận được.
  Kiểm tra `result.success` và `result.metadata["error"]` để xử lý lỗi cụ thể.
- **`max_concurrency`** là giới hạn thực thi đồng thời, không phải giới hạn số task.
  Có thể `fan_out(1000 tasks)` với `max_concurrency=8` — 8 task chạy song song, 992 còn lại đợi.
- Nếu pool không có agent nào (hoặc không agent nào match `tag_filter`), raise `ValueError` ngay.
- Không dùng `asyncio` — nội bộ dùng `anyio.create_task_group()` và `anyio.Semaphore()`.
