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

**Cơ chế truyền prompt:** `ReActStrategy` tự ghép `intent.action + chuỗi observations` vào
`task.payload["message"]` rồi gọi `agent_pool.dispatch(task)` mỗi bước. Agent chỉ cần đọc
`task.payload["message"]` và forward vào LLM. Agent không biết mình đang ở bước mấy.

```python
import os
import anyio
from dataclasses import dataclass, field

from uaaf import (
    AgentPool, BaseAgent, AgentResult, Task,
    ExecutionContext, ContextScope, Cost,
    StructuredIntent, ComplexityLevel,
)
from uaaf.cognitive.strategies.react import ReActStrategy
from uaaf.cognitive.verifier import VerificationResult
from uaaf.providers.llm import ILLMProvider, CompletionRequest, Message


# --- Prompt cho LLM: dạy nó dùng ACTION:/DONE: ---
_SYSTEM_PROMPT = """\
Bạn là chuyên gia phân tích cổ phiếu. Trả lời theo một trong hai format:
  ACTION: <bước cần thực hiện tiếp theo>
  DONE: <khuyến nghị cuối cùng với lý do>

Chỉ trả DONE khi đã có đủ thông tin để đưa ra khuyến nghị rõ ràng."""


# --- Provider factory: OpenAI nếu có API key, Fake nếu không ---
def build_provider() -> ILLMProvider:
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        from uaaf.providers.adapters.openai import OpenAIProvider
        return OpenAIProvider(api_key=api_key)  # type: ignore[return-value]
    from uaaf._testing.fakes import FakeLLMProvider
    from uaaf.providers.llm import Response, TokenUsage
    # Demo mode: mô phỏng luồng ACTION → ACTION → DONE
    return FakeLLMProvider(responses=[  # type: ignore[return-value]
        Response("ACTION: Lấy giá AAPL hiện tại và volume 30 ngày", "fake", TokenUsage(80, 20)),
        Response("ACTION: Tìm 5 bài báo về AAPL trong 7 ngày qua", "fake", TokenUsage(90, 25)),
        Response("ACTION: Phân tích sentiment từ các bài báo trên", "fake", TokenUsage(100, 30)),
        Response("DONE: Khuyến nghị MUA — giá $185 ở vùng hỗ trợ mạnh, sentiment tích cực 72%, volume tăng 15%", "fake", TokenUsage(120, 40)),
    ])


# --- Agent động: gọi LLM thật với prompt từ ReActStrategy ---
@dataclass
class StockResearchAgent(BaseAgent):
    llm: ILLMProvider = field(default_factory=build_provider)

    async def _execute(self, task: Task, ctx: ExecutionContext) -> AgentResult:
        # ReActStrategy đã ghép: intent.action + "\nObservations:\n" + chuỗi ACTION cũ
        user_prompt = task.payload.get("message", "")

        request = CompletionRequest(
            model="gpt-4o-mini",
            messages=[
                Message(role="system", content=_SYSTEM_PROMPT),
                Message(role="user",   content=user_prompt),
            ],
            max_tokens=256,
            temperature=0.2,  # thấp để output có format nhất quán
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
        llm=build_provider(),               # OpenAI hoặc Fake tuỳ OPENAI_API_KEY
        cost_tracker=CostTracker(CostPolicy()),
        tracer=Tracer("demo", InMemorySpanExporter()),
        audit_logger=AuditLogger(),
        rate_limiter=RateLimiter(RatePolicy(rps=10.0, burst=5)),
    )

    pool = AgentPool(max_concurrency=2)
    pool.register(agent)

    strategy = ReActStrategy(max_steps=6)

    intent = StructuredIntent(
        intent_type="stock_analysis",
        action="Nên mua cổ phiếu AAPL không? Phân tích giá, tin tức, và sentiment.",
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
    print(result.content)      # "DONE: Khuyến nghị MUA..."
    print(result.reasoning)    # chuỗi ACTION steps — dùng để audit


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
