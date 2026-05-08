# Pattern 1: Prompt Chaining — `ReActStrategy`

## Pattern là gì?

Prompt Chaining (chuỗi prompt) là kỹ thuật chia một yêu cầu phức tạp thành nhiều bước xử lý tuần tự,
trong đó output của bước trước trở thành input của bước tiếp theo.
UAAF triển khai pattern này qua **ReAct loop** (Reasoning + Acting):
mỗi vòng lặp, agent nhận toàn bộ lịch sử quan sát hiện tại, tự quyết định bước tiếp theo là
`ACTION:<hành động>` hay `DONE:<câu trả lời>`. Vòng lặp kết thúc khi agent trả về tín hiệu `DONE:`
hoặc đạt giới hạn `max_steps`.

## Khi nào nên dùng?

- Yêu cầu cần suy luận nhiều bước trước khi có câu trả lời cuối cùng.
- Bước sau phụ thuộc vào kết quả bước trước (không thể song song hóa).
- Cần giữ lại chuỗi quan sát (chain-of-thought) để trace lỗi hoặc audit.
- `intent.complexity >= ComplexityLevel.MEDIUM`.
- Ví dụ: gỡ lỗi code, tra cứu thông tin đa nguồn, lên kế hoạch từng bước.

## UAAF triển khai như thế nào?

| Thành phần | Vị trí |
|-----------|--------|
| `ReActStrategy` | `uaaf/cognitive/strategies/react.py` |
| `ICognitiveStrategy` (protocol) | `uaaf/cognitive/strategy.py` |
| `ComplexityLevel` | `uaaf/intent/models.py` |
| `IAgentPool.dispatch()` | `uaaf/cognitive/strategy.py` |

**Luồng thực thi bên trong `ReActStrategy.execute()`:**

```
Vòng lặp (tối đa max_steps lần):
  1. Xây dựng prompt = intent + tất cả observations hiện tại
  2. agent_pool.dispatch(task)  ← gọi LLM
  3. Nếu output bắt đầu bằng "DONE:" → return CognitiveResult ngay
  4. Nếu output bắt đầu bằng "ACTION:" → thêm vào observations, tiếp tục
Hết vòng lặp → trả về kết quả cuối với confidence=0.5
```

## Ví dụ code

```python
import anyio
from uaaf.cognitive.strategies.react import ReActStrategy
from uaaf.execution.pool import AgentPool
from uaaf.execution.agent import BaseAgent, AgentResult, Task
from uaaf.intent.models import StructuredIntent, ComplexityLevel
from uaaf.cognitive.verifier import IVerifier, VerificationResult
from uaaf.runtime.context import ExecutionContext, ContextScope
from uaaf.observability.cost import Cost


# --- Minimal fake agent: echoes DONE sau 2 bước ---
class StepAgent(BaseAgent):
    agent_id = "step-agent"

    def __init__(self):
        self._call = 0

    async def execute(self, task: Task, context: ExecutionContext) -> AgentResult:
        self._call += 1
        if self._call < 2:
            output = "ACTION: look up more data"
        else:
            output = "DONE: Paris là thủ đô của Pháp"
        return AgentResult(task_id=task.task_id, output=output, cost=Cost.zero())


# --- Minimal fake verifier ---
class PassVerifier:
    verifier_id = "pass"
    async def verify(self, output, context, metadata=None):
        return VerificationResult(passed=True, confidence=0.95)


async def main():
    pool = AgentPool(max_concurrency=4)
    pool.register(StepAgent())

    strategy = ReActStrategy(max_steps=6)

    intent = StructuredIntent(
        intent_type="query",
        action="Thủ đô của Pháp là gì?",
        entities={"country": "France"},
        complexity=ComplexityLevel.MEDIUM,
        confidence=0.9,
    )
    context = ExecutionContext(
        scope=ContextScope(user_id="u1", session_id="s1", domain="geo"),
        correlation_id="demo-react-01",
    )

    result = await strategy.execute(intent, context, pool, PassVerifier())
    print(result.content)      # "Paris là thủ đô của Pháp"
    print(result.confidence)   # 0.9
    print(result.strategy_id)  # "react"


anyio.run(main)
```

## Interface chính

```python
class ReActStrategy:
    strategy_id: str = "react"               # REACT constant
    max_steps: int                           # default=6, giới hạn số vòng lặp

    def applicable(
        self,
        intent: StructuredIntent,
        context: ExecutionContext,
    ) -> bool:
        # True khi intent.complexity >= ComplexityLevel.MEDIUM
        ...

    def estimate_cost(
        self,
        intent: StructuredIntent,
        context: ExecutionContext,
    ) -> CostEstimate:
        # steps_est = max_steps; usd_est = 0.001
        ...

    async def execute(
        self,
        intent: StructuredIntent,
        context: ExecutionContext,
        agent_pool: IAgentPool,   # dispatch() được gọi mỗi bước
        verifier: IVerifier,      # không dùng trong vòng lặp, chỉ dùng sau khi DONE
    ) -> CognitiveResult:
        # CognitiveResult.reasoning = chuỗi observations đã tích lũy
        ...
```

## Lưu ý quan trọng

- Agent phải trả về chuỗi bắt đầu bằng `DONE:` để kết thúc vòng lặp sớm; nếu không,
  strategy chạy đủ `max_steps` và trả `confidence=0.5`.
- Mỗi bước gọi `agent_pool.dispatch()` một lần — chi phí tỉ lệ tuyến tính với số bước.
- `CognitiveResult.reasoning` chứa toàn bộ chuỗi observations — hữu ích cho logging/audit.
- Không dùng `asyncio` trong `uaaf/` — nội bộ dùng `anyio`. Khi gọi từ `examples/` có thể
  dùng `anyio.run()` hoặc `asyncio.run()`.
