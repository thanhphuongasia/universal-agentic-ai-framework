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

```python
import anyio
from uaaf import (
    AgentPool, BaseAgent, AgentResult, Task,
    ExecutionContext, ContextScope, Cost,
    StructuredIntent, ComplexityLevel,
)
from uaaf.cognitive.strategies.evaluator_optimizer import EvaluatorOptimizerStrategy
from uaaf.cognitive.verifiers.pipeline import VerifierPipeline, PipelineMode
from uaaf.cognitive.verifier import VerificationResult


# --- Flashcard generator agent ---
class FlashcardAgent(BaseAgent):
    _attempt: int = 0

    async def _execute(self, task: Task, ctx: ExecutionContext) -> AgentResult:
        feedback = task.payload.get("message", "")
        self._attempt += 1

        if self._attempt == 1:
            # Lần đầu: thiếu ví dụ
            card = (
                "Q: Supervised Learning là gì?\n"
                "A: Học máy dùng dữ liệu có nhãn để train model dự đoán.\n"
                "Difficulty: beginner"
            )
        elif "thiếu ví dụ" in feedback:
            # Vòng 2: thêm ví dụ theo feedback
            card = (
                "Q: Supervised Learning là gì?\n"
                "A: Học máy dùng dữ liệu có nhãn để train model dự đoán output mới.\n"
                "   Ví dụ: phân loại email spam/not-spam dựa trên 10,000 email đã gán nhãn.\n"
                "Difficulty: beginner"
            )
        else:
            card = task.payload.get("message", "Q: ?\nA: ?\nDifficulty: ?")

        return AgentResult(task_id=task.task_id, output=card, cost=Cost.zero())


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
        cost_tracker=CostTracker(CostPolicy()),
        tracer=Tracer("demo", InMemorySpanExporter()),
        audit_logger=AuditLogger(),
        rate_limiter=RateLimiter(RatePolicy(rps=100.0, burst=10)),
    )
    pool = AgentPool(max_concurrency=2)
    pool.register(agent)

    # --- Pipeline mode: ALL_PASS — cả 3 tiêu chí phải đạt ---
    strict_verifier = VerifierPipeline(
        verifiers=[QuestionFormatVerifier(), ExampleVerifier(), DifficultyVerifier()],
        mode=PipelineMode.ALL_PASS,
    )

    # --- Pipeline mode: THRESHOLD — ít nhất 2/3 phải pass ---
    lenient_verifier = VerifierPipeline(
        verifiers=[QuestionFormatVerifier(), ExampleVerifier(), DifficultyVerifier()],
        mode=PipelineMode.THRESHOLD,
        threshold_count=2,
    )

    strategy = EvaluatorOptimizerStrategy(max_rounds=3)

    intent = StructuredIntent(
        intent_type="flashcard_generation",
        action="Tạo flashcard về Supervised Learning cho người mới học ML",
        entities={"topic": "supervised_learning", "level": "beginner"},
        complexity=ComplexityLevel.HIGH,
        confidence=0.92,
    )
    ctx = ExecutionContext(
        scope=ContextScope(user_id="student-01", session_id="s1", domain="flashcard"),
        correlation_id="flashcard-ml-beginner",
    )

    # Dùng strict_verifier: cả 3 tiêu chí đều phải đạt
    result = await strategy.execute(intent, ctx, pool, strict_verifier)
    print(result.strategy_id)   # "evaluator_optimizer"
    print(result.confidence)    # >= 0.85 sau vòng 2 (có ví dụ)
    print(result.content)       # flashcard đã được refine

    # Chi phí ước tính trước khi chạy
    estimate = strategy.estimate_cost(intent, ctx)
    print(f"Dự kiến: {estimate.steps_est} bước (max_rounds×2), ~${estimate.usd_est:.4f}")


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
