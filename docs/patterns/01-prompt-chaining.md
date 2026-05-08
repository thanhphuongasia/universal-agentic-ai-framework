# Pattern 1: Prompt Chaining — `ReActStrategy`

## Pattern là gì?

Prompt Chaining chia một yêu cầu phức tạp thành nhiều bước xử lý tuần tự, output của bước trước
là input của bước tiếp theo. UAAF triển khai qua **ReAct loop** (Reasoning + Acting): mỗi vòng
agent nhận toàn bộ lịch sử quan sát, quyết định `ACTION:<hành động>` hay `DONE:<câu trả lời>`.

## Khi nào nên dùng?

- Bước sau **phụ thuộc** kết quả bước trước — không thể song song hoá.
- Cần chuỗi suy luận (chain-of-thought) để trace lỗi hoặc audit.
- `intent.complexity >= ComplexityLevel.MEDIUM`.

**Không phù hợp khi**: các bước độc lập nhau → dùng Pattern 3 (Parallelization).

## UAAF triển khai như thế nào?

| Thành phần | Vị trí |
|-----------|--------|
| `ReActStrategy` | `uaaf/cognitive/strategies/react.py` |
| `ICognitiveStrategy` | `uaaf/cognitive/strategy.py` |

**Luồng bên trong `ReActStrategy.execute()`:**

```
Vòng lặp (tối đa max_steps):
  1. Prompt = intent + tất cả observations hiện tại
  2. agent_pool.dispatch(task) → LLM
  3. Output bắt đầu "DONE:" → return CognitiveResult ngay
  4. Output bắt đầu "ACTION:" → thêm vào observations, tiếp tục
Hết max_steps → trả kết quả cuối, confidence=0.5
```

## Ví dụ: Stock Research — "Nên mua AAPL không?"

Nghiên cứu cổ phiếu điển hình gồm nhiều bước phụ thuộc nhau:
**giá hiện tại → tin tức → phân tích sentiment → khuyến nghị**.
Mỗi bước cần kết quả bước trước → ReAct là lựa chọn đúng.

```python
import anyio
from uaaf import (
    AgentPool, BaseAgent, AgentResult, Task,
    ExecutionContext, ContextScope, Cost,
    StructuredIntent, ComplexityLevel,
)
from uaaf.cognitive.strategies.react import ReActStrategy
from uaaf.cognitive.verifier import VerificationResult


# --- Stock research agent: mô phỏng multi-step LLM ---
class StockResearchAgent(BaseAgent):
    _steps: list[str]

    def __post_init__(self) -> None:
        # Mỗi phần tử là response cho từng bước ReAct
        self._steps = [
            "ACTION: Lấy giá AAPL hiện tại",
            "ACTION: Tìm tin tức AAPL trong 7 ngày qua",
            "ACTION: Phân tích sentiment từ 3 bài báo tìm được",
            "DONE: Khuyến nghị MUA — giá $185 ở vùng hỗ trợ, sentiment tích cực 72%",
        ]
        self._call = 0

    async def _execute(self, task: Task, ctx: ExecutionContext) -> AgentResult:
        response = self._steps[min(self._call, len(self._steps) - 1)]
        self._call += 1
        return AgentResult(task_id=task.task_id, output=response, cost=Cost.zero())


class PassVerifier:
    verifier_id = "pass"
    async def verify(self, output: str, ctx: ExecutionContext, metadata=None):
        return VerificationResult(passed=True, confidence=0.92)


async def main():
    from uaaf.observability.audit import AuditLogger
    from uaaf.observability.cost import CostPolicy, CostTracker
    from uaaf.observability.rate_limit import RateLimiter, RatePolicy
    from uaaf.observability.tracer import Tracer
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    agent = StockResearchAgent(
        agent_id="stock-researcher",
        cost_tracker=CostTracker(CostPolicy()),
        tracer=Tracer("demo", InMemorySpanExporter()),
        audit_logger=AuditLogger(),
        rate_limiter=RateLimiter(RatePolicy(rps=100.0, burst=10)),
    )

    pool = AgentPool(max_concurrency=2)
    pool.register(agent)

    strategy = ReActStrategy(max_steps=6)

    intent = StructuredIntent(
        intent_type="stock_analysis",
        action="Nên mua cổ phiếu AAPL không?",
        entities={"ticker": "AAPL", "currency": "USD"},
        complexity=ComplexityLevel.MEDIUM,
        confidence=0.9,
    )
    ctx = ExecutionContext(
        scope=ContextScope(user_id="trader-01", session_id="s1", domain="stock"),
        correlation_id="stock-research-aapl",
    )

    result = await strategy.execute(intent, ctx, pool, PassVerifier())
    print(result.strategy_id)  # "react"
    print(result.content)      # "Khuyến nghị MUA — giá $185..."
    print(result.reasoning)    # chuỗi ACTION steps đã tích lũy — dùng để audit


anyio.run(main)
```

**Use case khác phù hợp Pattern 1:**
- **Todo Pro**: "Tại sao tôi hay trễ deadline?" → bước 1: lấy task history → bước 2: tìm pattern → bước 3: phân tích nguyên nhân → bước 4: đề xuất giải pháp
- **Coding Practice**: Gỡ lỗi code nhiều bước — mỗi observation là kết quả chạy test, bước tiếp theo fix dựa trên lỗi vừa thấy

## Interface chính

```python
class ReActStrategy:
    strategy_id: str = "react"
    max_steps: int   # default=6

    def applicable(self, intent: StructuredIntent, ctx: ExecutionContext) -> bool:
        # True khi intent.complexity >= ComplexityLevel.MEDIUM
        ...

    async def execute(
        self,
        intent: StructuredIntent,
        ctx: ExecutionContext,
        agent_pool: IAgentPool,  # dispatch() gọi mỗi bước
        verifier: IVerifier,
    ) -> CognitiveResult:
        # CognitiveResult.reasoning = chuỗi ACTION observations đã tích lũy
        ...
```

## Lưu ý quan trọng

- Agent phải trả `DONE:` để kết thúc sớm; nếu không, chạy đủ `max_steps` và `confidence=0.5`.
- Mỗi bước = 1 lần gọi LLM — chi phí tỉ lệ tuyến tính với số bước.
- `CognitiveResult.reasoning` chứa toàn bộ observations — hữu ích cho logging/audit.
