# Pattern 5: Evaluator-Optimizer — `EvaluatorOptimizerStrategy` + `VerifierPipeline`

## Pattern là gì?

Evaluator-Optimizer tự động cải thiện chất lượng output qua vòng lặp **generate → evaluate → refine**.
Thay vì chấp nhận kết quả đầu tiên, strategy sinh output, đánh giá qua verifier, dùng feedback
để tinh chỉnh prompt cho vòng tiếp theo — cho đến khi đạt chất lượng hoặc hết `max_rounds`.

Hai thành phần phối hợp:
- **`EvaluatorOptimizerStrategy`**: điều phối vòng lặp generate → verify → refine.
- **`VerifierPipeline`**: chạy nhiều verifier và tổng hợp theo `ALL_PASS`, `ANY_PASS`, hoặc `THRESHOLD`.

## Khi nào nên dùng?

- Output cần đạt tiêu chuẩn chất lượng cao có thể kiểm tra tự động.
- `intent.complexity == ComplexityLevel.HIGH`.
- Chấp nhận chi phí cao hơn (`max_rounds × 2` lần gọi LLM).

**Không phù hợp khi**: tiêu chí chất lượng cần human review — chi phí LLM không đủ bù đắp.

## UAAF triển khai như thế nào?

```
Vòng lặp (tối đa max_rounds):
  1. Prompt = intent + feedback từ vòng trước (rỗng ở vòng đầu)
  2. agent_pool.dispatch(task) → output
  3. verifier.verify(output) → VerificationResult(passed, confidence, feedback)
  4. Nếu confidence > best → cập nhật best_output
  5. passed==True → return ngay  |  passed==False → feedback → vòng tiếp
Hết max_rounds → return best_output (confidence cao nhất đạt được)
```

## Ví dụ: Flashcard System — Sinh flashcard chất lượng cao

Flashcard tốt cần: câu hỏi rõ ràng, câu trả lời đủ ngắn gọn, có ví dụ minh hoạ, độ khó đúng level.
Những tiêu chí này có thể kiểm tra tự động → Evaluator-Optimizer là lựa chọn đúng.

**Cơ chế truyền prompt:** `EvaluatorOptimizerStrategy` tự ghép `intent.action + feedback` vào
`task.payload["message"]` rồi gọi `agent_pool.dispatch(task)` mỗi vòng. Agent chỉ đọc
`task.payload["message"]` và forward vào LLM — không cần biết vòng mấy hay feedback là gì.

```python
import os
import anyio
from dataclasses import dataclass, field

from uaaf import (
    AgentPool, BaseAgent, AgentResult, Task,
    ExecutionContext, ContextScope, Cost,
    StructuredIntent, ComplexityLevel,
)
from uaaf.cognitive.strategies.evaluator_optimizer import EvaluatorOptimizerStrategy
from uaaf.cognitive.verifiers.pipeline import VerifierPipeline, PipelineMode
from uaaf.cognitive.verifier import VerificationResult
from uaaf.providers.llm import ILLMProvider, CompletionRequest, Message


_SYSTEM_PROMPT = """\
Tạo một flashcard học tập theo format sau (bắt buộc đủ 3 phần):
  Q: <câu hỏi rõ ràng, cụ thể>
  A: <câu trả lời ngắn gọn> + Ví dụ: <ví dụ minh hoạ cụ thể>
  Difficulty: <beginner|intermediate|advanced>

Nếu được cung cấp feedback, hãy sửa flashcard theo đúng feedback đó."""


def build_provider() -> ILLMProvider:
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        from uaaf.providers.adapters.openai import OpenAIProvider
        return OpenAIProvider(api_key=api_key)  # type: ignore[return-value]
    from uaaf._testing.fakes import FakeLLMProvider
    from uaaf.providers.llm import Response, TokenUsage
    # Vòng 1: thiếu ví dụ; Vòng 2: đủ sau khi nhận feedback
    return FakeLLMProvider(responses=[  # type: ignore[return-value]
        Response(
            "Q: Supervised Learning là gì?\nA: Học máy dùng dữ liệu có nhãn.\nDifficulty: beginner",
            "fake", TokenUsage(100, 40),
        ),
        Response(
            "Q: Supervised Learning là gì?\nA: Học máy dùng dữ liệu có nhãn để dự đoán output mới.\n   Ví dụ: phân loại spam/not-spam từ 10k email đã gán nhãn.\nDifficulty: beginner",
            "fake", TokenUsage(110, 60),
        ),
    ])


# --- Agent động: đọc prompt từ strategy, gọi LLM ---
@dataclass
class FlashcardAgent(BaseAgent):
    llm: ILLMProvider = field(default_factory=build_provider)

    async def _execute(self, task: Task, ctx: ExecutionContext) -> AgentResult:
        # EvaluatorOptimizerStrategy đã ghép: "intent.action\nPrevious feedback: ..."
        user_prompt = task.payload.get("message", "")

        request = CompletionRequest(
            model="gpt-4o-mini",
            messages=[
                Message(role="system", content=_SYSTEM_PROMPT),
                Message(role="user",   content=user_prompt),
            ],
            max_tokens=300,
            temperature=0.3,  # đủ creative nhưng vẫn follow format
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


# --- Verifier 1: câu hỏi phải bắt đầu bằng "Q:" ---
class QuestionFormatVerifier:
    verifier_id = "question-format"

    async def verify(self, output: str, ctx: ExecutionContext, metadata=None):
        ok = output.strip().startswith("Q:") and "A:" in output
        return VerificationResult(
            passed=ok,
            confidence=0.95 if ok else 0.2,
            feedback="" if ok else "Flashcard phải có 'Q:' và 'A:' rõ ràng",
        )


# --- Verifier 2: phải có ví dụ minh hoạ ---
class ExampleVerifier:
    verifier_id = "has-example"

    async def verify(self, output: str, ctx: ExecutionContext, metadata=None):
        has_example = "ví dụ" in output.lower() or "example" in output.lower()
        return VerificationResult(
            passed=has_example,
            confidence=0.9 if has_example else 0.4,
            feedback="" if has_example else "thiếu ví dụ minh hoạ — thêm 'Ví dụ: ...' vào phần A:",
        )


# --- Verifier 3: có độ khó ---
class DifficultyVerifier:
    verifier_id = "has-difficulty"

    async def verify(self, output: str, ctx: ExecutionContext, metadata=None):
        has_diff = "difficulty" in output.lower() or "độ khó" in output.lower()
        return VerificationResult(
            passed=has_diff,
            confidence=0.85 if has_diff else 0.5,
            feedback="" if has_diff else "Thiếu trường Difficulty",
        )


async def main():
    from uaaf.observability.audit import AuditLogger
    from uaaf.observability.cost import CostPolicy, CostTracker
    from uaaf.observability.rate_limit import RateLimiter, RatePolicy
    from uaaf.observability.tracer import Tracer
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    agent = FlashcardAgent(
        agent_id="flashcard-gen",
        llm=build_provider(),
        cost_tracker=CostTracker(CostPolicy()),
        tracer=Tracer("demo", InMemorySpanExporter()),
        audit_logger=AuditLogger(),
        rate_limiter=RateLimiter(RatePolicy(rps=10.0, burst=5)),
    )
    pool = AgentPool(max_concurrency=2)
    pool.register(agent)

    strict_verifier = VerifierPipeline(
        verifiers=[QuestionFormatVerifier(), ExampleVerifier(), DifficultyVerifier()],
        mode=PipelineMode.ALL_PASS,
    )

    strategy = EvaluatorOptimizerStrategy(max_rounds=3)

    intent = StructuredIntent(
        intent_type="flashcard_generation",
        # Strategy sẽ ghép string này + feedback vào task.payload["message"]
        action="Tạo flashcard về Supervised Learning cho người mới học ML",
        entities={"topic": "supervised_learning", "level": "beginner"},
        complexity=ComplexityLevel.HIGH,
        confidence=0.92,
    )
    ctx = ExecutionContext(
        scope=ContextScope(user_id="student-01", session_id="s1", domain="flashcard"),
        correlation_id="flashcard-ml-beginner",
    )

    result = await strategy.execute(intent, ctx, pool, strict_verifier)
    print(result.strategy_id)   # "evaluator_optimizer"
    print(result.confidence)    # >= 0.85 sau vòng 2 (LLM đã thêm ví dụ theo feedback)
    print(result.content)       # flashcard đã được LLM refine dựa trên feedback verifier


anyio.run(main)
```

**Use case khác phù hợp Pattern 5:**
- **Code Analysis**: Sinh báo cáo phân tích → verify có đủ mục (complexity, issues, suggestion) → refine nếu thiếu
- **Stock Trading**: Sinh trading signal → verify: có entry price, stop-loss, take-profit → refine nếu thiếu risk management
- **Todo Pro**: Sinh kế hoạch tuần → verify: mỗi ngày có ≥ 1 task, tổng thời gian ≤ 8h/ngày → refine nếu overload

## Interface chính

```python
class EvaluatorOptimizerStrategy:
    strategy_id: str = "evaluator_optimizer"
    max_rounds: int  # default=3

    def applicable(self, intent: StructuredIntent, ctx: ExecutionContext) -> bool:
        # True khi intent.complexity == ComplexityLevel.HIGH
        ...

    async def execute(
        self,
        intent: StructuredIntent,
        ctx: ExecutionContext,
        agent_pool: IAgentPool,  # dispatch() gọi mỗi vòng generate
        verifier: IVerifier,     # verify() gọi mỗi vòng evaluate
    ) -> CognitiveResult:
        # Luôn trả best_output — không bao giờ trả chuỗi rỗng
        ...


class PipelineMode(StrEnum):
    ALL_PASS  = "all_pass"   # tất cả verifier phải pass; confidence = min(all)
    ANY_PASS  = "any_pass"   # ít nhất 1 pass; confidence = max(all)
    THRESHOLD = "threshold"  # pass_count >= threshold_count; confidence = avg(all)


class VerifierPipeline:
    def __init__(
        self,
        verifiers: list[IVerifier],
        mode: PipelineMode = PipelineMode.ALL_PASS,
        threshold_count: int = 1,
    ) -> None: ...

    async def verify(
        self, output: str, ctx: ExecutionContext, metadata=None
    ) -> VerificationResult:
        # VerificationResult.feedback = join feedback của verifier không pass
        ...


@dataclass
class VerificationResult:
    passed: bool
    confidence: float   # 0.0–1.0
    feedback: str = ""  # actionable — dùng làm prompt refinement vòng tiếp
```

## Lưu ý quan trọng

- **Feedback phải actionable**: verifier cần trả feedback cụ thể ("thiếu stop-loss price") không phải chung chung ("lỗi") — agent dùng feedback này để refine.
- **Best-of-N**: dù không pass trong `max_rounds`, strategy trả output có confidence cao nhất — không trả chuỗi rỗng.
- **Pipeline rỗng**: `VerifierPipeline(verifiers=[])` → `passed=True, confidence=1.0` — tắt verification tạm thời.
- **Chọn mode**:
  - `ALL_PASS`: yêu cầu nghiêm ngặt (code phải pass lint + type check + test)
  - `ANY_PASS`: tiêu chí tùy chọn (flashcard cần ví dụ HOẶC analogy)
  - `THRESHOLD`: majority vote (3/5 reviewer đồng ý)
- Chi phí tối đa = `max_rounds × (1 generate + 1 verify)` lần gọi LLM.
