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

## RYUU triển khai như thế nào?

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

**Cơ chế truyền prompt:** `fan_out()` chỉ dispatch task — agent tự xây prompt từ `task.payload`.
Không có strategy nào pre-build prompt cho Pattern 3; agent phải đọc payload và gọi LLM trực tiếp.

```python
import json
import os
import anyio
from dataclasses import dataclass, field

from ryuu import (
    AgentPool, BaseAgent, AgentResult, Task,
    ExecutionContext, ContextScope, Cost,
)
from ryuu.providers.llm import ILLMProvider, CompletionRequest, Message


_SYSTEM_PROMPT = """\
Phân tích file Python sau. Trả về JSON với các trường:
  file, classes (int), methods (int), docstring_coverage (float 0-1), complexity (LOW|MEDIUM|HIGH), issues (list[str])
Chỉ trả JSON, không thêm text khác."""


def build_provider() -> ILLMProvider:
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        from ryuu.providers.adapters.openai import OpenAIProvider
        return OpenAIProvider(api_key=api_key)  # type: ignore[return-value]
    from ryuu._testing.fakes import FakeLLMProvider
    from ryuu.providers.llm import Response, TokenUsage
    fake_report = json.dumps({"file": "?", "classes": 3, "methods": 12,
                              "docstring_coverage": 0.75, "complexity": "MEDIUM", "issues": []})
    return FakeLLMProvider(default_content=fake_report)  # type: ignore[return-value]


@dataclass
class FileAnalysisAgent(BaseAgent):
    """Phân tích 1 file Python bằng LLM."""
    llm: ILLMProvider = field(default_factory=build_provider)

    async def _execute(self, task: Task, ctx: ExecutionContext) -> AgentResult:
        filepath = task.payload["filepath"]
        source   = task.payload.get("source", f"# (source của {filepath})")

        request = CompletionRequest(
            model="gpt-4o-mini",
            messages=[
                Message(role="system", content=_SYSTEM_PROMPT),
                Message(role="user",   content=f"File: {filepath}\n\n```python\n{source}\n```"),
            ],
            max_tokens=512,
            temperature=0.0,   # JSON output cần deterministic
        )
        response = await self.llm.complete(request)

        return AgentResult(
            task_id=task.task_id,
            output=response.content,   # JSON string
            cost=Cost(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                usd=round((response.usage.input_tokens + response.usage.output_tokens) * 1.5e-7, 8),
                provider="openai",
                model=response.model,
            ),
        )


async def main():
    from pathlib import Path
    from ryuu.observability.audit import AuditLogger
    from ryuu.observability.cost import CostPolicy, CostTracker
    from ryuu.observability.rate_limit import RateLimiter, RatePolicy
    from ryuu.observability.tracer import Tracer
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    provider = build_provider()  # dùng chung 1 provider (stateless HTTP calls)

    def make_agent(name: str) -> FileAnalysisAgent:
        return FileAnalysisAgent(
            agent_id=name,
            llm=provider,
            cost_tracker=CostTracker(CostPolicy()),
            tracer=Tracer("demo", InMemorySpanExporter()),
            audit_logger=AuditLogger(),
            rate_limiter=RateLimiter(RatePolicy(rps=10.0, burst=20)),
        )

    pool = AgentPool(max_concurrency=3)  # 3 worker, phân phối round-robin
    pool.register(make_agent("analyzer-0"))
    pool.register(make_agent("analyzer-1"))
    pool.register(make_agent("analyzer-2"))

    # Đọc source thật và nhét vào payload để agent forward vào prompt
    files = [
        "ryuu/execution/agent.py",
        "ryuu/execution/pool.py",
        "ryuu/cognitive/strategies/react.py",
        "ryuu/observability/cost.py",
    ]
    tasks = [
        Task(
            task_id=f"file-{i}",
            payload={
                "filepath": f,
                "source": Path(f).read_text() if Path(f).exists() else f"# {f} not found",
            },
        )
        for i, f in enumerate(files)
    ]

    ctx = ExecutionContext(
        scope=ContextScope(user_id="ci-bot", session_id="scan-001", domain="code_analysis"),
        correlation_id="batch-file-scan",
    )

    results = await pool.fan_out(tasks, ctx, on_error="collect")

    successes = [r for r in results if r.success]
    failures  = [r for r in results if not r.success]
    print(f"Phân tích thành công: {len(successes)}/{len(tasks)} file")

    for r in successes:
        try:
            data = json.loads(r.output)
            print(f"  {data['file']}: {data['classes']} class, "
                  f"docstring {data['docstring_coverage']:.0%}, {data['complexity']}")
        except json.JSONDecodeError:
            print(f"  {r.task_id}: LLM trả non-JSON — {r.output[:60]}")

    for r in failures:
        print(f"  FAIL {r.task_id}: {r.metadata.get('error', '?')}")


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
