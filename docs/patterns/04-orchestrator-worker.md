# Pattern 4: Orchestrator-Worker — `ParallelFanoutStrategy` + `AgentPool`

## Pattern là gì?

Orchestrator-Worker gồm một thành phần trung tâm (orchestrator) phân rã nhiệm vụ phức tạp
thành subtask, phân phối cho nhiều worker xử lý song song, rồi tổng hợp kết quả.

UAAF triển khai qua `ParallelFanoutStrategy`:
1. **Phân rã** (`ISubtaskBuilder`): tạo 1 `Task` cho mỗi entity trong `intent.entities`.
2. **Dispatch song song** (`fan_out(on_error="collect")`): worker thất bại không hủy các worker khác.
3. **Tổng hợp**: lấy output từ `result.success == True`.
4. **Verify**: kiểm tra chất lượng kết quả tổng hợp.

**Khác Pattern 3**: Pattern 3 chỉ thuần túy dispatch parallel. Pattern này thêm **phân rã intent** và **tổng hợp có kiểm soát chất lượng**.

## Khi nào nên dùng?

- `intent.complexity == HIGH` và `len(entities) > 1`.
- Mỗi entity xử lý độc lập nhau.
- Cần tổng hợp kết quả thành một output thống nhất.
- Chấp nhận partial success (một vài worker lỗi, kết quả vẫn được trả).

## UAAF triển khai như thế nào?

| Thành phần | Vị trí |
|-----------|--------|
| `ParallelFanoutStrategy` | `uaaf/cognitive/strategies/parallel.py` |
| `ISubtaskBuilder` (protocol) | `uaaf/cognitive/strategies/parallel.py` |
| `EntitySubtaskBuilder` (default) | `uaaf/cognitive/strategies/parallel.py` |

**Luồng thực thi:**
```
intent.entities = {"auth": "...", "payment": "...", "user": "..."}
    │
    ├── EntitySubtaskBuilder.build_subtasks()
    │   → [Task("subtask-auth"), Task("subtask-payment"), Task("subtask-user")]
    │
    ├── AgentPool.fan_out(subtasks, on_error="collect")
    │   → [AgentResult(ok), AgentResult(success=False), AgentResult(ok)]
    │
    ├── aggregate: join output từ success==True
    │   combined = "auth report\n\nuser report"
    │
    ├── verifier.verify(combined)
    │   → VerificationResult(passed=True, confidence=0.87)
    │
    └── CognitiveResult(content=combined, confidence=0.87, strategy_id="parallel_fanout")
```

**Điều kiện `applicable()`:**
```python
intent.complexity == ComplexityLevel.HIGH  AND  len(intent.entities) > 1
```

## Ví dụ: Code Analysis — Phân tích toàn bộ codebase UAAF

Đây chính là use case của `examples/code_analysis/`: orchestrate phân tích song song cho
từng Python class, mỗi class là một entity trong intent.

```python
import anyio
from uaaf import (
    AgentPool, BaseAgent, AgentResult, Task,
    ExecutionContext, ContextScope, Cost,
    StructuredIntent, ComplexityLevel,
)
from uaaf.cognitive.strategies.parallel import (
    ParallelFanoutStrategy,
    ISubtaskBuilder,
)
from uaaf.cognitive.verifier import VerificationResult


# --- Worker: phân tích 1 Python class ---
class ClassAnalysisWorker(BaseAgent):
    async def _execute(self, task: Task, ctx: ExecutionContext) -> AgentResult:
        class_name  = task.payload["entity_key"]
        module_path = task.payload["entity_value"]
        # Thực tế: đọc source, gọi LLM phân tích complexity/docstring/issues
        report = (
            f"Class {class_name} ({module_path}): "
            f"complexity=MEDIUM, 8 methods, docstring coverage 62%"
        )
        return AgentResult(task_id=task.task_id, output=report, cost=Cost.zero())


# --- Custom subtask builder: thêm metadata ---
class ClassSubtaskBuilder:
    def build_subtasks(
        self, intent: StructuredIntent, ctx: ExecutionContext
    ) -> list[Task]:
        return [
            Task(
                task_id=f"class-{name}",
                payload={
                    "entity_key": name,
                    "entity_value": path,
                    "project": ctx.scope.domain,
                },
            )
            for name, path in intent.entities.items()
        ]


class ReportVerifier:
    verifier_id = "report-completeness"
    async def verify(self, output: str, ctx: ExecutionContext, metadata=None):
        # Kiểm tra kết quả tổng hợp có đủ thông tin không
        has_content = len(output.strip()) > 50
        return VerificationResult(
            passed=has_content,
            confidence=0.9 if has_content else 0.3,
            feedback="" if has_content else "Kết quả quá ngắn — có thể nhiều worker bị lỗi",
        )


async def main():
    from uaaf.observability.audit import AuditLogger
    from uaaf.observability.cost import CostPolicy, CostTracker
    from uaaf.observability.rate_limit import RateLimiter, RatePolicy
    from uaaf.observability.tracer import Tracer
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    def make_worker(name: str) -> ClassAnalysisWorker:
        return ClassAnalysisWorker(
            agent_id=name,
            cost_tracker=CostTracker(CostPolicy()),
            tracer=Tracer("demo", InMemorySpanExporter()),
            audit_logger=AuditLogger(),
            rate_limiter=RateLimiter(RatePolicy(rps=100.0, burst=20)),
        )

    pool = AgentPool(max_concurrency=4)
    for i in range(4):
        pool.register(make_worker(f"class-analyst-{i}"))

    # Dùng custom builder để có thêm metadata
    strategy = ParallelFanoutStrategy(subtask_builder=ClassSubtaskBuilder())

    # Entities = các class cần phân tích trong codebase UAAF
    intent = StructuredIntent(
        intent_type="code_analysis",
        action="Phân tích toàn bộ class trong codebase UAAF",
        entities={
            "AgentPool":                "uaaf/execution/pool.py",
            "BaseAgent":                "uaaf/execution/agent.py",
            "ReActStrategy":            "uaaf/cognitive/strategies/react.py",
            "EvaluatorOptimizerStrategy": "uaaf/cognitive/strategies/evaluator_optimizer.py",
            "ModelRouter":              "uaaf/providers/router.py",
        },
        complexity=ComplexityLevel.HIGH,
        confidence=0.95,
    )
    ctx = ExecutionContext(
        scope=ContextScope(user_id="ci-bot", session_id="s1", domain="uaaf"),
        correlation_id="codebase-analysis-run-01",
    )

    # applicable() kiểm tra: HIGH + 5 entities > 1 → True
    assert strategy.applicable(intent, ctx)

    result = await strategy.execute(intent, ctx, pool, ReportVerifier())
    print(result.strategy_id)   # "parallel_fanout"
    print(result.confidence)    # 0.9 (nếu verify passed)
    print(result.content[:200]) # combined report từ 5 worker

    # estimate_cost trước khi chạy (hữu ích để pre-flight check)
    estimate = strategy.estimate_cost(intent, ctx)
    print(f"Dự kiến: {estimate.steps_est} bước, ~${estimate.usd_est:.4f}")


anyio.run(main)
```

**Use case khác phù hợp Pattern 4:**
- **Flashcard System**: `entities = {"chapter_1": "...", "chapter_2": "...", "chapter_3": "..."}` → mỗi chapter sinh flashcard song song → tổng hợp thành deck
- **Stock Trading**: `entities = {"AAPL": "...", "MSFT": "...", "GOOGL": "..."}` → phân tích song song → tổng hợp portfolio report
- **Todo Pro batch import**: `entities = {"project_alpha": [...], "project_beta": [...]}` → xử lý song song → import tất cả

## Interface chính

```python
@runtime_checkable
class ISubtaskBuilder(Protocol):
    def build_subtasks(
        self, intent: StructuredIntent, ctx: ExecutionContext
    ) -> list[Task]: ...
    # Task.payload có "entity_key" và "entity_value" (EntitySubtaskBuilder mặc định)


@dataclass
class ParallelFanoutStrategy:
    strategy_id: str = "parallel_fanout"
    subtask_builder: ISubtaskBuilder = field(default_factory=EntitySubtaskBuilder)

    def applicable(self, intent: StructuredIntent, ctx: ExecutionContext) -> bool:
        # True: complexity==HIGH AND len(entities) > 1
        ...

    def estimate_cost(self, intent: StructuredIntent, ctx: ExecutionContext) -> CostEstimate:
        # steps_est = len(entities); usd_est = 0.0001 * n
        ...

    async def execute(
        self,
        intent: StructuredIntent,
        ctx: ExecutionContext,
        agent_pool: IAgentPool,  # cần có fan_out(); fallback về dispatch() nếu không có
        verifier: IVerifier,
    ) -> CognitiveResult: ...
```

## Lưu ý quan trọng

- **`on_error="collect"`** là mặc định: partial failure không hỏng toàn bộ kết quả.
- **Custom `ISubtaskBuilder`**: khi cần thêm metadata vào payload hoặc logic phân rã phức tạp hơn, inject qua constructor.
- **Backward compat**: pool không có `fan_out()` → fallback về dispatch tuần tự qua `hasattr(agent_pool, "fan_out")`.
- **Confidence**: `0.5 × verification.confidence` khi verify không pass — dấu hiệu output không hoàn chỉnh.
