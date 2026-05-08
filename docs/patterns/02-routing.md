# Pattern 2: Routing — `StrategySelector` + `ModelRouter`

## Pattern là gì?

Routing là pattern phân luồng request đến handler phù hợp nhất dựa trên đặc điểm của request đó.
UAAF có hai lớp routing hoạt động độc lập:

1. **Strategy Routing** (`StrategySelector`): nhận `StructuredIntent` và chọn `ICognitiveStrategy`
   đầu tiên mà `applicable()` trả về `True`. Thứ tự đăng ký strategies quyết định ưu tiên.

2. **Model Routing** (`ModelRouter`): nhận `ModelTier` (CHEAP / STANDARD / POWERFUL) và trả về
   `ILLMProvider` tương ứng. Nếu provider bị lỗi, `CircuitBreaker` ngắt mạch và router chuyển
   sang `fallback` provider.

Hai lớp này tách biệt nhau: `StrategySelector` chọn *cách xử lý*, `ModelRouter` chọn *LLM nào dùng*.

## Khi nào nên dùng?

- Hệ thống có nhiều loại request với yêu cầu xử lý khác nhau (đơn giản vs phức tạp).
- Cần kiểm soát chi phí: request đơn giản dùng model rẻ hơn (`CHEAP`), request phức tạp dùng
  model mạnh hơn (`POWERFUL`).
- Muốn thêm strategy mới mà không sửa code cũ (Open/Closed Principle).
- Cần circuit breaker tự động khi provider LLM gặp sự cố.

## UAAF triển khai như thế nào?

| Thành phần | Vị trí |
|-----------|--------|
| `StrategySelector` | `uaaf/intent/selector.py` |
| `ModelRouter` | `uaaf/providers/router.py` |
| `ICognitiveStrategy` (protocol) | `uaaf/cognitive/strategy.py` |
| `ILLMProvider` (protocol) | `uaaf/providers/llm.py` |
| `ModelTier` | `uaaf/intent/models.py` |
| `CircuitBreaker` | `uaaf/providers/circuit_breaker.py` |

**Luồng Strategy Routing:**

```
StructuredIntent (complexity=HIGH, entities={...})
    │
    ▼
StrategySelector.select(intent, context)
    ├── ParallelFanoutStrategy.applicable()? → complexity==HIGH AND len(entities)>1 → True ✓
    ├── EvaluatorOptimizerStrategy.applicable()? → (không đến đây)
    └── ... (dừng tại strategy đầu tiên applicable)
    │
    ▼
ICognitiveStrategy (ParallelFanoutStrategy)
```

**Luồng Model Routing:**

```
intent.suggested_model_tier = ModelTier.CHEAP
    │
    ▼
ModelRouter.route(ModelTier.CHEAP)
    ├── CircuitBreaker.is_available()? → True → trả FakeLLMProvider("gpt-4o-mini")
    └── Nếu breaker mở → trả fallback provider
```

## Ví dụ code

```python
import anyio
from uaaf.intent.selector import StrategySelector
from uaaf.cognitive.strategies.direct import DirectStrategy
from uaaf.cognitive.strategies.react import ReActStrategy
from uaaf.cognitive.strategies.parallel import ParallelFanoutStrategy
from uaaf.cognitive.strategies.evaluator_optimizer import EvaluatorOptimizerStrategy
from uaaf.providers.router import ModelRouter
from uaaf.intent.models import (
    StructuredIntent, ComplexityLevel, ModelTier, DIRECT
)
from uaaf.runtime.context import ExecutionContext, ContextScope


# --- Khởi tạo StrategySelector với thứ tự ưu tiên ---
# Chú ý: ParallelFanoutStrategy kiểm tra cả complexity VÀ len(entities) > 1,
# vì vậy đặt trước EvaluatorOptimizerStrategy là an toàn.
selector = StrategySelector(strategies=[
    ParallelFanoutStrategy(),       # HIGH + nhiều entity
    EvaluatorOptimizerStrategy(),   # HIGH (fallback khi 1 entity)
    ReActStrategy(),                # MEDIUM+
    DirectStrategy(),               # tất cả (fallback cuối)
])

context = ExecutionContext(
    scope=ContextScope(user_id="u1", session_id="s1", domain="demo"),
    correlation_id="routing-demo",
)

# --- Strategy routing: request đơn giản ---
simple_intent = StructuredIntent(
    intent_type="query",
    action="Hôm nay là thứ mấy?",
    entities={},
    complexity=ComplexityLevel.LOW,
    confidence=0.95,
    suggested_strategy=DIRECT,
    suggested_model_tier=ModelTier.CHEAP,
)
strategy = selector.select(simple_intent, context)
print(type(strategy).__name__)   # DirectStrategy

# --- Strategy routing: request phức tạp nhiều entity ---
complex_intent = StructuredIntent(
    intent_type="analysis",
    action="So sánh hiệu suất của 3 hệ thống",
    entities={"sys_a": "nginx", "sys_b": "caddy", "sys_c": "haproxy"},
    complexity=ComplexityLevel.HIGH,
    confidence=0.88,
    suggested_model_tier=ModelTier.POWERFUL,
)
strategy = selector.select(complex_intent, context)
print(type(strategy).__name__)   # ParallelFanoutStrategy


# --- Model routing ---
from uaaf._testing.fakes import FakeLLMProvider

cheap_provider  = FakeLLMProvider(default_content="cheap model response")
strong_provider = FakeLLMProvider(default_content="powerful model response")
fallback        = FakeLLMProvider(default_content="fallback response")

router = ModelRouter(
    providers={
        ModelTier.CHEAP:     cheap_provider,
        ModelTier.STANDARD:  FakeLLMProvider(),
        ModelTier.POWERFUL:  strong_provider,
    },
    fallback=fallback,
    failure_threshold=3,
    recovery_timeout=30.0,
)

# Route theo tier từ intent
provider = router.route(simple_intent.suggested_model_tier)   # → cheap_provider
print(provider is cheap_provider)   # True

provider = router.route(complex_intent.suggested_model_tier)  # → strong_provider
print(provider is strong_provider)  # True
```

## Interface chính

```python
# ---- StrategySelector ----
class StrategySelector:
    def __init__(self, strategies: list[ICognitiveStrategy]) -> None:
        # Thứ tự trong list = thứ tự ưu tiên
        ...

    def select(
        self,
        intent: StructuredIntent,
        context: ExecutionContext,
    ) -> ICognitiveStrategy:
        # Trả strategy đầu tiên mà applicable() == True
        # Raise ValueError nếu không có strategy nào phù hợp
        ...


# ---- ModelRouter ----
class ModelRouter:
    def __init__(
        self,
        providers: dict[ModelTier, ILLMProvider],
        fallback: ILLMProvider | None = None,
        failure_threshold: int = 5,     # số lần lỗi trước khi mở circuit breaker
        recovery_timeout: float = 60.0, # giây trước khi thử lại
    ) -> None: ...

    def route(self, model_tier: ModelTier) -> ILLMProvider:
        # Trả provider còn available; nếu circuit open → trả fallback
        # Raise DegradedError nếu không có fallback
        ...

    def record_failure(self, provider_id: str) -> None: ...
    def record_success(self, provider_id: str) -> None: ...

    # ModelRouter cũng implement ILLMProvider trực tiếp:
    async def complete(self, request: CompletionRequest) -> Response: ...
    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]: ...
    async def embed(self, text: str, model: str | None = None) -> Embedding: ...


# ---- ModelTier ----
class ModelTier(StrEnum):
    CHEAP    = "cheap"      # gpt-4o-mini, haiku, v.v.
    STANDARD = "standard"   # gpt-4o, claude-3-5-sonnet, v.v.
    POWERFUL = "powerful"   # gpt-4, claude-opus, v.v.
```

## Lưu ý quan trọng

- **Thứ tự strategies quan trọng**: `StrategySelector` dừng tại strategy `applicable()` đầu tiên.
  Đặt strategies đặc biệt (hẹp hơn) trước strategies chung (rộng hơn). `DirectStrategy` luôn
  trả `True` nên phải đặt cuối.
- **ModelRouter là ILLMProvider**: có thể truyền trực tiếp vào bất kỳ nơi nào nhận `ILLMProvider`.
  Router tự xác định tier từ tên model (`"haiku"` → `CHEAP`, `"opus"` → `POWERFUL`).
- **Circuit Breaker**: `record_failure()` được gọi tự động trong `ModelRouter.complete()`.
  Không cần gọi thủ công trừ khi wrap router trong custom code.
