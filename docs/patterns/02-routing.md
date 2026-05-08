# Pattern 2: Routing — `StrategySelector` + `ModelRouter`

## Pattern là gì?

Routing phân luồng request đến handler phù hợp nhất. UAAF có hai lớp routing độc lập:

1. **Strategy Routing** (`StrategySelector`): chọn `ICognitiveStrategy` đầu tiên mà `applicable()` trả `True`. Thứ tự đăng ký = thứ tự ưu tiên.
2. **Model Routing** (`ModelRouter`): chọn LLM provider theo `ModelTier` (CHEAP / STANDARD / POWERFUL). Nếu provider lỗi, `CircuitBreaker` tự chuyển sang fallback.

Hai lớp tách biệt: `StrategySelector` chọn *cách xử lý*, `ModelRouter` chọn *LLM nào dùng*.

## Khi nào nên dùng?

- Hệ thống có nhiều loại request với yêu cầu xử lý khác nhau.
- Cần kiểm soát chi phí: request đơn giản dùng model rẻ (`CHEAP`), phức tạp dùng model mạnh (`POWERFUL`).
- Muốn thêm strategy mới mà không sửa code cũ.

## UAAF triển khai như thế nào?

| Thành phần | Vị trí |
|-----------|--------|
| `StrategySelector` | `uaaf/intent/selector.py` |
| `ModelRouter` | `uaaf/providers/router.py` |
| `CircuitBreaker` | `uaaf/providers/circuit_breaker.py` |

**Luồng Strategy Routing:**
```
StructuredIntent(complexity=HIGH, entities={"a":1, "b":2})
    │
    ▼
StrategySelector.select()
    ├── ParallelFanoutStrategy.applicable()? HIGH + 2 entities → True ✓ (dừng)
    ├── EvaluatorOptimizerStrategy.applicable()? (không đến đây)
    └── ...
```

**Luồng Model Routing:**
```
ModelTier.CHEAP → ModelRouter.route() → gpt-4o-mini (nếu circuit CLOSED)
                                      → fallback     (nếu circuit OPEN)
```

## Ví dụ: Todo Pro — Phân luồng request theo độ phức tạp

Todo Pro nhận đủ loại request: "Thêm task mua sữa" (đơn giản, rẻ) đến "Phân tích pattern trễ deadline của tôi" (phức tạp, cần model mạnh). Routing tự chọn strategy + model tier đúng.

```python
from uaaf import (
    ExecutionContext, ContextScope,
    StructuredIntent, ComplexityLevel, ModelTier,
)
from uaaf.intent.selector import StrategySelector
from uaaf.cognitive.strategies import (
    DirectStrategy,
    ReActStrategy,
    EvaluatorOptimizerStrategy,
    ParallelFanoutStrategy,
)
from uaaf.intent.models import DIRECT, REACT, EVALUATOR_OPTIMIZER, PARALLEL_FANOUT


# --- Khởi tạo StrategySelector: thứ tự = ưu tiên ---
# ParallelFanout phải đặt trước EvaluatorOptimizer vì cả hai applicable() với HIGH.
# DirectStrategy luôn applicable() → đặt cuối làm fallback.
selector = StrategySelector(strategies=[
    ParallelFanoutStrategy(),      # HIGH + nhiều entity
    EvaluatorOptimizerStrategy(),  # HIGH, 1 entity
    ReActStrategy(),               # MEDIUM+
    DirectStrategy(),              # LOW (fallback)
])

ctx = ExecutionContext(
    scope=ContextScope(user_id="user-42", session_id="s1", domain="todo"),
    correlation_id="todo-routing-demo",
)

# --- Request 1: Thêm task đơn giản → DirectStrategy + CHEAP ---
add_task_intent = StructuredIntent(
    intent_type="mutation",
    action="Thêm task: mua sữa tươi",
    entities={"task": "mua sữa tươi"},
    complexity=ComplexityLevel.LOW,
    confidence=0.98,
    suggested_strategy=DIRECT,
    suggested_model_tier=ModelTier.CHEAP,
)
strategy = selector.select(add_task_intent, ctx)
print(type(strategy).__name__)          # DirectStrategy
print(add_task_intent.suggested_model_tier)  # ModelTier.CHEAP

# --- Request 2: Đánh dấu done nhiều task cùng lúc → ParallelFanout + CHEAP ---
batch_done_intent = StructuredIntent(
    intent_type="mutation",
    action="Đánh dấu hoàn thành tất cả task hôm nay",
    entities={"task_1": "mua sữa", "task_2": "họp standup", "task_3": "review PR"},
    complexity=ComplexityLevel.HIGH,
    confidence=0.95,
    suggested_strategy=PARALLEL_FANOUT,
    suggested_model_tier=ModelTier.CHEAP,
)
strategy = selector.select(batch_done_intent, ctx)
print(type(strategy).__name__)          # ParallelFanoutStrategy

# --- Request 3: Phân tích productivity → EvaluatorOptimizer + POWERFUL ---
analysis_intent = StructuredIntent(
    intent_type="analysis",
    action="Phân tích tại sao tôi hay trễ deadline và đề xuất cải thiện",
    entities={"user_id": "user-42"},
    complexity=ComplexityLevel.HIGH,
    confidence=0.88,
    suggested_strategy=EVALUATOR_OPTIMIZER,
    suggested_model_tier=ModelTier.POWERFUL,
)
strategy = selector.select(analysis_intent, ctx)
print(type(strategy).__name__)          # EvaluatorOptimizerStrategy

# --- Model Routing: chọn LLM provider theo tier ---
from uaaf._testing.fakes import FakeLLMProvider
from uaaf.providers.router import ModelRouter

router = ModelRouter(
    providers={
        ModelTier.CHEAP:    FakeLLMProvider(default_content="mini model"),
        ModelTier.STANDARD: FakeLLMProvider(default_content="standard model"),
        ModelTier.POWERFUL: FakeLLMProvider(default_content="powerful model"),
    },
    fallback=FakeLLMProvider(default_content="fallback"),
    failure_threshold=3,
    recovery_timeout=30.0,
)

cheap_llm    = router.route(ModelTier.CHEAP)    # → gpt-4o-mini provider
powerful_llm = router.route(ModelTier.POWERFUL) # → gpt-4/claude-opus provider
```

**Use case khác phù hợp Pattern 2:**
- **Stock Trading**: LOW = giá hiện tại → `DirectStrategy + CHEAP`; HIGH = phân tích danh mục → `ParallelFanout + POWERFUL`
- **Flashcard System**: MEDIUM = tạo 1 flashcard → `ReAct + STANDARD`; HIGH batch = tạo 20 flashcard cho nhiều chương → `ParallelFanout + CHEAP`

## Interface chính

```python
class StrategySelector:
    def __init__(self, strategies: list[ICognitiveStrategy]) -> None:
        # Thứ tự trong list = ưu tiên; DirectStrategy phải đặt cuối
        ...

    def select(self, intent: StructuredIntent, ctx: ExecutionContext) -> ICognitiveStrategy:
        # Trả strategy đầu tiên applicable(); raise ValueError nếu không có
        ...


class ModelRouter:
    def __init__(
        self,
        providers: dict[ModelTier, ILLMProvider],
        fallback: ILLMProvider | None = None,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
    ) -> None: ...

    def route(self, model_tier: ModelTier) -> ILLMProvider:
        # Circuit CLOSED → provider chính; Circuit OPEN → fallback
        # Raise DegradedError nếu không có fallback
        ...

    # ModelRouter cũng implement ILLMProvider — dùng trực tiếp thay provider:
    async def complete(self, request: CompletionRequest) -> Response: ...
```

## Lưu ý quan trọng

- **Thứ tự strategies quan trọng**: `DirectStrategy.applicable()` luôn `True` — đặt cuối.
- **`ModelRouter` là `ILLMProvider`**: truyền thẳng vào `OpenAIProvider`-like slot, router tự xác định tier từ tên model.
- **`suggested_model_tier`** trong `StructuredIntent` là gợi ý từ `LLMIntentAnalyzer` — caller vẫn có thể override.
