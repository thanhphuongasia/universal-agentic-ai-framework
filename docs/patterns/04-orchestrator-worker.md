# Pattern 4: Orchestrator-Worker — `ParallelFanoutStrategy` + `AgentPool`

## Pattern là gì?

Orchestrator-Worker gồm một thành phần trung tâm (orchestrator) phân rã nhiệm vụ phức tạp
thành subtask, phân phối cho nhiều worker xử lý song song, rồi tổng hợp kết quả.

RYUU triển khai qua `ParallelFanoutStrategy`:
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

## RYUU triển khai như thế nào?

| Thành phần | Vị trí |
|-----------|--------|
| `ParallelFanoutStrategy` | `ryuu/cognitive/strategies/parallel.py` |
| `ISubtaskBuilder` (protocol) | `ryuu/cognitive/strategies/parallel.py` |
| `EntitySubtaskBuilder` (default) | `ryuu/cognitive/strategies/parallel.py` |

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

## Ví dụ: Code Analysis — Phân tích toàn bộ codebase RYUU

Đây chính là use case của `examples/code_analysis/`: orchestrate phân tích song song cho
từng Python class, mỗi class là một entity trong intent.

**Cơ chế truyền prompt:** `EntitySubtaskBuilder` tạo task với `payload["entity_key"]` và
`payload["entity_value"]`. Worker đọc hai trường này để xây prompt, gọi LLM, trả JSON report.
`ParallelFanoutStrategy` tổng hợp các JSON đó thành một output duy nhất.

```python
import json
import os
import anyio
from dataclasses import dataclass, field

from ryuu import (
    AgentPool, BaseAgent, AgentResult, Task,
    ExecutionContext, ContextScope, Cost,
    StructuredIntent, ComplexityLevel,
)
from ryuu.cognitive.strategies.parallel import ParallelFanoutStrategy, ISubtaskBuilder
from ryuu.cognitive.verifier import VerificationResult
from ryuu.providers.llm import ILLMProvider, CompletionRequest, Message


_SYSTEM_PROMPT = """\
Phân tích Python class dưới đây. Trả về JSON với các trường:
  class (str), module (str), complexity (LOW|MEDIUM|HIGH),
  method_count (int), has_docstring (bool), issues (list[str]),
  refactor_priority (LOW|MEDIUM|HIGH)
Chỉ trả JSON, không thêm text khác."""


def build_provider() -> ILLMProvider:
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        from ryuu.providers.adapters.openai import OpenAIProvider
        return OpenAIProvider(api_key=api_key)  # type: ignore[return-value]
    from ryuu._testing.fakes import FakeLLMProvider
    from ryuu.providers.llm import Response, TokenUsage
    def _fake(name: str, module: str) -> Response:
        return Response(
            json.dumps({"class": name, "module": module, "complexity": "MEDIUM",
                        "method_count": 8, "has_docstring": True,
                        "issues": [], "refactor_priority": "LOW"}),
            "fake", TokenUsage(80, 60),
        )
    # FakeLLMProvider trả responses theo thứ tự — đủ cho 5 entity
    return FakeLLMProvider(responses=[  # type: ignore[return-value]
        _fake("AgentPool", "ryuu/execution/pool.py"),
        _fake("BaseAgent", "ryuu/execution/agent.py"),
        _fake("ReActStrategy", "ryuu/cognitive/strategies/react.py"),
        _fake("EvaluatorOptimizerStrategy", "ryuu/cognitive/strategies/evaluator_optimizer.py"),
        _fake("ModelRouter", "ryuu/providers/router.py"),
    ])


# --- Worker: phân tích 1 Python class ---
@dataclass
class ClassAnalysisWorker(BaseAgent):
    llm: ILLMProvider = field(default_factory=build_provider)

    async def _execute(self, task: Task, ctx: ExecutionContext) -> AgentResult:
        class_name  = task.payload["entity_key"]
        module_path = task.payload["entity_value"]

        # Thực tế: đọc source từ module_path rồi nhét vào prompt
        source_hint = f"# class {class_name} in {module_path}"

        request = CompletionRequest(
            model="gpt-4o-mini",
            messages=[
                Message(role="system", content=_SYSTEM_PROMPT),
                Message(role="user",   content=f"Class: {class_name}\nModule: {module_path}\n\n{source_hint}"),
            ],
            max_tokens=512,
            temperature=0.0,
        )
        response = await self.llm.complete(request)

        return AgentResult(
            task_id=task.task_id,
            output=response.content,
            cost=Cost(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                usd=round((response.usage.input_tokens + response.usage.output_tokens) * 1.5e-7, 8),
                provider="openai",
                model=response.model,
            ),
        )


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
    from ryuu.observability.audit import AuditLogger
    from ryuu.observability.cost import CostPolicy, CostTracker
    from ryuu.observability.rate_limit import RateLimiter, RatePolicy
    from ryuu.observability.tracer import Tracer
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    provider = build_provider()  # 1 provider dùng chung — stateless, thread-safe

    def make_worker(name: str) -> ClassAnalysisWorker:
        return ClassAnalysisWorker(
            agent_id=name,
            llm=provider,
            cost_tracker=CostTracker(CostPolicy()),
            tracer=Tracer("demo", InMemorySpanExporter()),
            audit_logger=AuditLogger(),
            rate_limiter=RateLimiter(RatePolicy(rps=10.0, burst=20)),
        )

    pool = AgentPool(max_concurrency=4)
    for i in range(4):
        pool.register(make_worker(f"class-analyst-{i}"))

    strategy = ParallelFanoutStrategy()  # dùng EntitySubtaskBuilder mặc định

    intent = StructuredIntent(
        intent_type="code_analysis",
        action="Phân tích toàn bộ class trong codebase RYUU",
        entities={
            "AgentPool":                  "ryuu/execution/pool.py",
            "BaseAgent":                  "ryuu/execution/agent.py",
            "ReActStrategy":              "ryuu/cognitive/strategies/react.py",
            "EvaluatorOptimizerStrategy": "ryuu/cognitive/strategies/evaluator_optimizer.py",
            "ModelRouter":                "ryuu/providers/router.py",
        },
        complexity=ComplexityLevel.HIGH,
        confidence=0.95,
    )
    ctx = ExecutionContext(
        scope=ContextScope(user_id="ci-bot", session_id="s1", domain="ryuu"),
        correlation_id="codebase-analysis-run-01",
    )

    result = await strategy.execute(intent, ctx, pool, ReportVerifier())
    print(result.strategy_id)   # "parallel_fanout"
    print(result.confidence)    # 0.9 (nếu verify passed)

    # combined = JSON của từng class, join bằng "\n\n"
    for chunk in result.content.split("\n\n"):
        try:
            data = json.loads(chunk)
            print(f"  {data['class']}: {data['complexity']}, priority={data['refactor_priority']}")
        except json.JSONDecodeError:
            pass


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
