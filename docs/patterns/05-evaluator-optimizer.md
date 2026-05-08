# Pattern 5: Evaluator-Optimizer — `EvaluatorOptimizerStrategy` + `VerifierPipeline`

## Pattern là gì?

Evaluator-Optimizer là pattern tự động cải thiện chất lượng output thông qua vòng lặp
**generate → evaluate → refine**. Thay vì chấp nhận kết quả đầu tiên, strategy liên tục
sinh output, đánh giá qua verifier, và dùng feedback từ verifier để tinh chỉnh prompt
cho vòng tiếp theo — cho đến khi output đạt chất lượng (`verification.passed == True`)
hoặc hết số vòng (`max_rounds`).

Hai thành phần phối hợp:

- **`EvaluatorOptimizerStrategy`**: điều phối vòng lặp generate→verify→refine.
- **`VerifierPipeline`**: chạy nhiều verifier song song và tổng hợp kết quả theo ba chế độ:
  `ALL_PASS` (mọi verifier phải pass), `ANY_PASS` (ít nhất 1 pass), hoặc `THRESHOLD`
  (số lượng pass >= ngưỡng).

## Khi nào nên dùng?

- Output cần đạt tiêu chuẩn chất lượng cao (code đúng syntax, văn bản không vi phạm policy, v.v.).
- Có thể định nghĩa được tiêu chí kiểm tra tự động (không cần human review mỗi vòng).
- `intent.complexity == ComplexityLevel.HIGH`.
- Chấp nhận chi phí cao hơn (tối đa `max_rounds × 2` lần gọi LLM: `max_rounds` generate + `max_rounds` verify).
- Ví dụ: sinh code và kiểm tra lint/test, tạo nội dung marketing và kiểm tra brand guidelines,
  sinh SQL và kiểm tra syntax + safety.

## UAAF triển khai như thế nào?

| Thành phần | Vị trí |
|-----------|--------|
| `EvaluatorOptimizerStrategy` | `uaaf/cognitive/strategies/evaluator_optimizer.py` |
| `VerifierPipeline` | `uaaf/cognitive/verifiers/pipeline.py` |
| `PipelineMode` | `uaaf/cognitive/verifiers/pipeline.py` |
| `IVerifier` (protocol) | `uaaf/cognitive/verifier.py` |
| `VerificationResult` | `uaaf/cognitive/verifier.py` |

**Luồng thực thi bên trong `EvaluatorOptimizerStrategy.execute()`:**

```
Vòng lặp (tối đa max_rounds lần):
    ┌─────────────────────────────────────────────┐
    │  1. Xây dựng prompt = intent + feedback      │
    │     (vòng đầu: không có feedback)            │
    │                                             │
    │  2. agent_pool.dispatch(task) → output       │
    │                                             │
    │  3. verifier.verify(output, context)         │
    │     → VerificationResult(passed, confidence, │
    │                          feedback)           │
    │                                             │
    │  4. Nếu confidence > best_confidence         │
    │     → cập nhật best_output                  │
    │                                             │
    │  5. Nếu passed == True → return ngay        │
    │     Nếu passed == False → feedback → lặp lại │
    └─────────────────────────────────────────────┘

Hết max_rounds → return best_output (confidence cao nhất đạt được)
```

## Ví dụ code

```python
import anyio
from uaaf.cognitive.strategies.evaluator_optimizer import EvaluatorOptimizerStrategy
from uaaf.cognitive.verifiers.pipeline import VerifierPipeline, PipelineMode
from uaaf.cognitive.verifier import IVerifier, VerificationResult
from uaaf.execution.pool import AgentPool
from uaaf.execution.agent import BaseAgent, AgentResult, Task
from uaaf.intent.models import StructuredIntent, ComplexityLevel
from uaaf.runtime.context import ExecutionContext, ContextScope
from uaaf.observability.cost import Cost


# --- Worker agent: sinh code Python ---
class CodeGenAgent(BaseAgent):
    agent_id = "code-gen"
    _attempt = 0

    async def execute(self, task: Task, context: ExecutionContext) -> AgentResult:
        self._attempt += 1
        feedback = task.payload.get("message", "")
        if "address feedback" in feedback and self._attempt >= 2:
            # Vòng 2 trở đi: cải thiện theo feedback
            code = "def add(a: int, b: int) -> int:\n    return a + b\n"
        else:
            # Vòng 1: code lỗi thiếu type hint
            code = "def add(a, b):\n    return a + b\n"
        return AgentResult(task_id=task.task_id, output=code, cost=Cost.zero())


# --- Verifier 1: kiểm tra type hint ---
class TypeHintVerifier:
    verifier_id = "type-hint"
    async def verify(self, output: str, context, metadata=None) -> VerificationResult:
        has_hints = "->" in output and ": int" in output
        return VerificationResult(
            passed=has_hints,
            confidence=0.95 if has_hints else 0.4,
            feedback="" if has_hints else "Thiếu type hints — thêm annotation cho tham số và return type",
        )


# --- Verifier 2: kiểm tra docstring ---
class DocstringVerifier:
    verifier_id = "docstring"
    async def verify(self, output: str, context, metadata=None) -> VerificationResult:
        has_doc = '"""' in output or "'''" in output
        return VerificationResult(
            passed=has_doc,
            confidence=0.9 if has_doc else 0.5,
            feedback="" if has_doc else "Thiếu docstring",
        )


async def main():
    pool = AgentPool(max_concurrency=2)
    pool.register(CodeGenAgent())

    # --- VerifierPipeline: chỉ cần 1 trong 2 verifier pass (ANY_PASS) ---
    verifier_any = VerifierPipeline(
        verifiers=[TypeHintVerifier(), DocstringVerifier()],
        mode=PipelineMode.ANY_PASS,
    )

    # --- VerifierPipeline: cả 2 phải pass (ALL_PASS) ---
    verifier_all = VerifierPipeline(
        verifiers=[TypeHintVerifier(), DocstringVerifier()],
        mode=PipelineMode.ALL_PASS,
    )

    # --- VerifierPipeline: ít nhất 2/3 verifier pass (THRESHOLD) ---
    verifier_threshold = VerifierPipeline(
        verifiers=[TypeHintVerifier(), DocstringVerifier(), TypeHintVerifier()],
        mode=PipelineMode.THRESHOLD,
        threshold_count=2,
    )

    strategy = EvaluatorOptimizerStrategy(max_rounds=3)

    intent = StructuredIntent(
        intent_type="code_generation",
        action="Viết hàm Python cộng hai số nguyên",
        entities={"language": "python", "function": "add"},
        complexity=ComplexityLevel.HIGH,
        confidence=0.92,
    )
    context = ExecutionContext(
        scope=ContextScope(user_id="u1", session_id="s1", domain="coding"),
        correlation_id="eo-demo",
    )

    # Dùng ANY_PASS: pass nếu có type hint HOẶC có docstring
    result = await strategy.execute(intent, context, pool, verifier_any)
    print(result.strategy_id)   # "evaluator_optimizer"
    print(result.confidence)    # >= 0.9 nếu pass sớm
    print(result.content)


anyio.run(main)
```

## Interface chính

```python
# ---- EvaluatorOptimizerStrategy ----
class EvaluatorOptimizerStrategy:
    strategy_id: str = "evaluator_optimizer"
    max_rounds: int  # default=3

    def applicable(
        self,
        intent: StructuredIntent,
        context: ExecutionContext,
    ) -> bool:
        # True khi intent.complexity == ComplexityLevel.HIGH
        ...

    def estimate_cost(
        self,
        intent: StructuredIntent,
        context: ExecutionContext,
    ) -> CostEstimate:
        # steps_est = max_rounds * 2 (generate + verify mỗi vòng)
        # usd_est = 0.005
        ...

    async def execute(
        self,
        intent: StructuredIntent,
        context: ExecutionContext,
        agent_pool: IAgentPool,   # gọi dispatch() mỗi vòng generate
        verifier: IVerifier,      # gọi verify() mỗi vòng evaluate
    ) -> CognitiveResult:
        # Trả output có confidence cao nhất đạt được trong max_rounds
        ...


# ---- VerifierPipeline ----
class PipelineMode(StrEnum):
    ALL_PASS  = "all_pass"   # min(confidence); tất cả phải pass
    ANY_PASS  = "any_pass"   # max(confidence); ít nhất 1 pass
    THRESHOLD = "threshold"  # avg(confidence); pass_count >= threshold_count

class VerifierPipeline:
    verifier_id: str = "pipeline"

    def __init__(
        self,
        verifiers: list[IVerifier],
        mode: PipelineMode = PipelineMode.ALL_PASS,
        threshold_count: int = 1,   # chỉ dùng khi mode=THRESHOLD
    ) -> None: ...

    async def verify(
        self,
        output: str,
        context: ExecutionContext,
        metadata: dict[str, Any] | None = None,
    ) -> VerificationResult:
        # Chạy tất cả verifier tuần tự, tổng hợp theo mode
        # VerificationResult.feedback = join các feedback của verifier không pass
        ...


# ---- VerificationResult ----
@dataclass
class VerificationResult:
    passed: bool
    confidence: float    # 0.0–1.0
    feedback: str = ""   # mô tả vấn đề cần sửa; empty string nếu passed
```

## Lưu ý quan trọng

- **Feedback loop**: `VerificationResult.feedback` được đưa vào prompt vòng tiếp theo.
  Verifier cần trả feedback cụ thể, actionable (không phải chỉ "lỗi") để agent có thể cải thiện.
- **Best-of-N**: dù không pass trong `max_rounds`, strategy vẫn trả `best_output` — output
  có `confidence` cao nhất trong tất cả các vòng. Không bao giờ trả chuỗi rỗng.
- **`VerifierPipeline` với list rỗng**: tự động trả `passed=True, confidence=1.0` — hữu ích
  khi muốn tạm thời tắt verification.
- **Chọn `PipelineMode`**: `ALL_PASS` cho yêu cầu nghiêm ngặt (mọi tiêu chí đều phải đạt);
  `ANY_PASS` khi tiêu chí tùy chọn; `THRESHOLD` khi cần majority vote.
- **Chi phí**: mỗi vòng gọi ít nhất 1 lần LLM (generate) + 1 lần verify (có thể gọi thêm LLM
  nếu verifier dùng LLM). Với `max_rounds=3`, chi phí gấp ~3× so với `DirectStrategy`.
- `EvaluatorOptimizerStrategy` và `ParallelFanoutStrategy` đều chỉ `applicable()` khi
  `complexity=HIGH` — trong `StrategySelector`, đặt `ParallelFanoutStrategy` trước nếu muốn
  ưu tiên fan-out khi có nhiều entity.
