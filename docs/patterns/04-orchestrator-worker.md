# Pattern 4: Orchestrator-Worker — `ParallelFanoutStrategy` + `AgentPool`

## Pattern là gì?

Orchestrator-Worker là pattern trong đó một thành phần trung tâm (orchestrator) phân rã một nhiệm
vụ phức tạp thành các công việc nhỏ hơn, phân phối cho nhiều worker xử lý song song, rồi tổng hợp
kết quả. UAAF triển khai pattern này qua `ParallelFanoutStrategy`:

1. **Phân rã** (`ISubtaskBuilder.build_subtasks()`): mặc định là `EntitySubtaskBuilder`, tạo
   một `Task` cho mỗi `entity` trong `intent.entities`.
2. **Dispatch song song** (`AgentPool.fan_out(on_error="collect")`): worker thất bại không hủy
   các worker khác — kết quả partial vẫn được tổng hợp.
3. **Tổng hợp**: chỉ lấy kết quả từ các worker thành công (`result.success == True`).
4. **Verify**: kết quả tổng hợp được đưa qua `verifier.verify()` để kiểm tra chất lượng.

Pattern này khác Pattern 3 (Parallelization) ở chỗ: orchestrator chịu trách nhiệm **phân rã**
và **tổng hợp**, trong khi Pattern 3 chỉ thuần túy dispatch parallel.

## Khi nào nên dùng?

- Intent có `complexity=HIGH` và nhiều hơn một entity (`len(entities) > 1`).
- Mỗi entity có thể xử lý hoàn toàn độc lập nhau.
- Cần tổng hợp kết quả từ nhiều worker thành một output thống nhất.
- Chấp nhận partial success: nếu một vài worker lỗi, kết quả vẫn được trả với output từ
  những worker thành công.
- Ví dụ: phân tích song song nhiều tài liệu/repo, gọi API cho nhiều entity, xử lý batch lớn.

## UAAF triển khai như thế nào?

| Thành phần | Vị trí |
|-----------|--------|
| `ParallelFanoutStrategy` | `uaaf/cognitive/strategies/parallel.py` |
| `ISubtaskBuilder` (protocol) | `uaaf/cognitive/strategies/parallel.py` |
| `EntitySubtaskBuilder` (default) | `uaaf/cognitive/strategies/parallel.py` |
| `AgentPool.fan_out()` | `uaaf/execution/pool.py` |
| `IVerifier` | `uaaf/cognitive/verifier.py` |

**Luồng thực thi bên trong `ParallelFanoutStrategy.execute()`:**

```
intent.entities = {"repo_a": "...", "repo_b": "...", "repo_c": "..."}
    │
    ├── subtask_builder.build_subtasks(intent, context)
    │       → [Task("subtask-repo_a"), Task("subtask-repo_b"), Task("subtask-repo_c")]
    │
    ├── agent_pool.fan_out(subtasks, context, on_error="collect")
    │       → [AgentResult(success=True, output="..."),
    │           AgentResult(success=False, metadata={"error": "timeout"}),
    │           AgentResult(success=True, output="...")]
    │
    ├── aggregate: lấy output từ result.success == True
    │       combined = "output_a\n\noutput_c"
    │
    ├── verifier.verify(combined, context)
    │       → VerificationResult(passed=True, confidence=0.85)
    │
    └── CognitiveResult(content=combined, confidence=0.85, strategy_id="parallel_fanout")
```

**Điều kiện `applicable()`:**

```python
intent.complexity == ComplexityLevel.HIGH  AND  len(intent.entities) > 1
```

Nếu chỉ có 1 entity và complexity=HIGH, `EvaluatorOptimizerStrategy` sẽ được chọn thay thế
(nếu đặt trong `StrategySelector` sau `ParallelFanoutStrategy`).

## Ví dụ code

```python
import anyio
from uaaf.cognitive.strategies.parallel import (
    ParallelFanoutStrategy,
    ISubtaskBuilder,
    EntitySubtaskBuilder,
)
from uaaf.execution.pool import AgentPool
from uaaf.execution.agent import BaseAgent, AgentResult, Task
from uaaf.intent.models import StructuredIntent, ComplexityLevel
from uaaf.cognitive.verifier import IVerifier, VerificationResult
from uaaf.runtime.context import ExecutionContext, ContextScope
from uaaf.observability.cost import Cost


# --- Worker agent: xử lý 1 entity ---
class RepoAnalyzer(BaseAgent):
    agent_id = "repo-analyzer"

    async def execute(self, task: Task, context: ExecutionContext) -> AgentResult:
        key   = task.payload.get("entity_key", "?")
        value = task.payload.get("entity_value", "?")
        output = f"Repo '{key}' ({value}): 142 commits, 3 open issues"
        return AgentResult(task_id=task.task_id, output=output, cost=Cost.zero())


# --- Verifier đơn giản ---
class LengthVerifier:
    verifier_id = "length"
    async def verify(self, output, context, metadata=None):
        passed = len(output) > 10
        return VerificationResult(passed=passed, confidence=0.9 if passed else 0.2)


# --- Custom ISubtaskBuilder (tùy chọn, thay vì EntitySubtaskBuilder mặc định) ---
class RepoSubtaskBuilder:
    """Tạo task cho mỗi repo với thêm metadata."""

    def build_subtasks(
        self, intent: StructuredIntent, context: ExecutionContext
    ) -> list[Task]:
        return [
            Task(
                task_id=f"repo-{key}",
                payload={
                    "entity_key": key,
                    "entity_value": val,
                    "correlation_id": context.correlation_id,
                },
            )
            for key, val in intent.entities.items()
        ]


async def main():
    pool = AgentPool(max_concurrency=4)
    pool.register(RepoAnalyzer())

    # Dùng default EntitySubtaskBuilder
    strategy = ParallelFanoutStrategy()

    # Hoặc dùng custom builder:
    # strategy = ParallelFanoutStrategy(subtask_builder=RepoSubtaskBuilder())

    intent = StructuredIntent(
        intent_type="analysis",
        action="Phân tích tất cả repositories",
        entities={
            "frontend": "github.com/org/ui",
            "backend":  "github.com/org/api",
            "infra":    "github.com/org/terraform",
        },
        complexity=ComplexityLevel.HIGH,
        confidence=0.9,
    )
    context = ExecutionContext(
        scope=ContextScope(user_id="u1", session_id="s1", domain="devops"),
        correlation_id="orch-worker-demo",
    )

    # Kiểm tra applicable trước (StrategySelector sẽ làm điều này tự động)
    assert strategy.applicable(intent, context)   # True: HIGH + 3 entities

    result = await strategy.execute(intent, context, pool, LengthVerifier())
    print(result.strategy_id)   # "parallel_fanout"
    print(result.confidence)    # 0.9 (nếu verify passed)
    print(result.content)       # combined output từ tất cả worker thành công


anyio.run(main)
```

## Interface chính

```python
# ---- ISubtaskBuilder Protocol ----
@runtime_checkable
class ISubtaskBuilder(Protocol):
    def build_subtasks(
        self,
        intent: StructuredIntent,
        context: ExecutionContext,
    ) -> list[Task]: ...


# ---- EntitySubtaskBuilder (default) ----
@dataclass
class EntitySubtaskBuilder:
    """Tạo 1 Task cho mỗi key-value trong intent.entities."""
    def build_subtasks(
        self, intent: StructuredIntent, context: ExecutionContext
    ) -> list[Task]:
        # task_id = f"subtask-{key}"
        # payload = {"entity_key": key, "entity_value": val}
        ...


# ---- ParallelFanoutStrategy ----
@dataclass
class ParallelFanoutStrategy:
    strategy_id: str = "parallel_fanout"
    subtask_builder: ISubtaskBuilder = field(default_factory=EntitySubtaskBuilder)

    def applicable(
        self,
        intent: StructuredIntent,
        context: ExecutionContext,
    ) -> bool:
        # True khi: intent.complexity == HIGH AND len(intent.entities) > 1
        ...

    def estimate_cost(
        self,
        intent: StructuredIntent,
        context: ExecutionContext,
    ) -> CostEstimate:
        # n = len(entities); steps_est = n; usd_est = 0.0001 * n
        ...

    async def execute(
        self,
        intent: StructuredIntent,
        context: ExecutionContext,
        agent_pool: IAgentPool,   # cần hỗ trợ fan_out() cho concurrent dispatch
        verifier: IVerifier,      # verify kết quả tổng hợp sau fan_out
    ) -> CognitiveResult:
        # Fallback về dispatch() tuần tự nếu pool không có fan_out()
        ...
```

## Lưu ý quan trọng

- **`on_error="collect"` là mặc định** trong `ParallelFanoutStrategy`: partial failure không
  làm hỏng toàn bộ kết quả. Kiểm tra `CognitiveResult.confidence` để biết chất lượng.
- **Backward compat**: nếu `agent_pool` là `IAgentPool` thuần (không có `fan_out`), strategy
  tự động fallback về dispatch tuần tự qua `hasattr(agent_pool, "fan_out")`.
- **Custom `ISubtaskBuilder`**: khi `EntitySubtaskBuilder` không đủ (cần thêm metadata, logic
  phân rã khác), inject custom builder qua constructor `ParallelFanoutStrategy(subtask_builder=...)`.
- **Confidence giảm khi verify không pass**: `confidence = 0.5 * verification.confidence`
  thay vì `verification.confidence` khi `verification.passed == False`.
- `estimate_cost()` tỉ lệ tuyến tính với số entity — hữu ích để pre-flight check trước khi gọi LLM tốn kém.
