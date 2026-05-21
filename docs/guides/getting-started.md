# Getting Started with RYUU

> **Goal**: Agent đầu tiên chạy trong < 5 phút.

---

## 1. Install

```bash
pip install ryuu                        # core only
pip install "ryuu[openai]"              # + OpenAI adapter
pip install "ryuu[anthropic]"           # + Anthropic adapter
pip install "ryuu[openai,anthropic]"    # cả hai
```

For development (clone + editable install):

```bash
git clone <your-repo>
cd ryuu-framework
pip install -e ".[dev]"
```

Verify:

```bash
python -c "import ryuu; print(ryuu.__version__)"
```

---

## 2. Khái niệm cốt lõi

```
Request
  └─→ IIntentAnalyzer  (phân tích intent → StructuredIntent)
        └─→ StrategySelector (chọn strategy dựa trên complexity)
              └─→ ICognitiveStrategy (DirectStrategy / ReActStrategy / EvaluatorOptimizerStrategy)
                    └─→ ILLMProvider (gọi LLM qua ILLMProvider interface)
                          └─→ IKnowledgeBackbone (đọc/ghi context)
```

Cross-cutting được inject vào `BaseAgent` — **product code không cần tự handle**:
- `CostTracker` — budget per user/domain/global
- `Tracer` — OpenTelemetry + correlation ID
- `AuditLogger` — tamper-proof JSONL hash chain
- `RateLimiter` — token bucket per scope

---

## 3. Agent đầu tiên (dùng FakeLLMProvider)

Snippet này không cần API key — dùng `FakeLLMProvider` để chạy ngay:

```python
import anyio
from dataclasses import dataclass, field

from ryuu._testing.fakes import FakeLLMProvider
from ryuu.execution.agent import BaseAgent, Task, AgentResult
from ryuu.observability.audit import AuditLogger
from ryuu.observability.cost import Cost, CostPolicy, CostTracker
from ryuu.observability.rate_limit import RateLimiter, RatePolicy
from ryuu.observability.tracer import Tracer
from ryuu.providers.llm import CompletionRequest, Message
from ryuu_workflow.context import ContextScope, ExecutionContext


@dataclass
class GreetingAgent(BaseAgent):
    llm: FakeLLMProvider = field(default_factory=FakeLLMProvider)

    async def _execute(self, task: Task, context: ExecutionContext) -> AgentResult:
        req = CompletionRequest(
            messages=[Message(role="user", content=str(task.payload.get("message", "")))],
            model="gpt-4o-mini",
        )
        response = await self.llm.complete(req)
        return AgentResult(
            task_id=task.task_id,
            output=response.content,
            cost=Cost(input_tokens=10, output_tokens=5, usd=0.0, provider="fake", model="fake"),
        )


async def main() -> None:
    scope = ContextScope(user_id="u1", session_id="s1", domain="demo")
    ctx = ExecutionContext(scope=scope, correlation_id="corr-001")

    agent = GreetingAgent(
        agent_id="greeter",
        cost_tracker=CostTracker(CostPolicy()),
        tracer=Tracer(),
        audit_logger=AuditLogger(),
        rate_limiter=RateLimiter(RatePolicy()),
    )

    result = await agent.execute(
        Task(task_id="t1", payload={"message": "Hello RYUU!"}),
        ctx,
    )
    print(result.output)


anyio.run(main)
```

---

## 4. Switch sang OpenAI thật

Thay `FakeLLMProvider` bằng `OpenAIProvider`:

```python
import os
from ryuu.providers.adapters.openai import OpenAIProvider

provider = OpenAIProvider(api_key=os.environ["OPENAI_API_KEY"])
```

Hoặc Anthropic:

```python
import os
from ryuu.providers.adapters.anthropic import AnthropicProvider

provider = AnthropicProvider(api_key=os.environ["ANTHROPIC_API_KEY"])
```

Inject vào agent thay `FakeLLMProvider` — interface giống hệt nhau, không cần thay đổi agent code.

---

## 5. ModelRouter (multi-provider + circuit breaker)

Khi cần route request theo cost tier và tự động fallback khi provider down:

```python
from ryuu.intent.models import ModelTier
from ryuu.providers.router import ModelRouter

router = ModelRouter(
    providers={
        ModelTier.CHEAP: cheap_provider,      # gpt-4o-mini, claude-haiku
        ModelTier.STANDARD: main_provider,    # gpt-4o
        ModelTier.POWERFUL: power_provider,   # claude-opus
    },
    fallback=backup_provider,
    failure_threshold=3,
    recovery_timeout=30.0,
)
```

`ModelRouter` tự detect tier từ model name trong `CompletionRequest.model`:
- `"gpt-4o-mini"`, `"claude-haiku-*"` → `CHEAP`
- `"claude-opus-*"` → `POWERFUL`
- Còn lại → `STANDARD`

---

## 6. Bước tiếp theo

| Mục tiêu | Đọc |
|---|---|
| Lưu context qua các request | [Cookbook: Todo App](../cookbook/01-todo-app.md) |
| Spaced repetition / scheduled batch | [Cookbook: Flashcard](../cookbook/02-flashcard-system.md) |
| Chạy code an toàn trong sandbox | [Cookbook: Coding Practice](../cookbook/03-coding-practice.md) |
| Audit trail + compliance | [Cookbook: Stock Trading](../cookbook/04-stock-trading.md) |
| Migrate từ legacy system | [Migration Guide](migration.md) |
