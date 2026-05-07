# Cookbook: Todo App

> **Validates**: `MemoryBackbone` + `DirectStrategy`
> **Complexity**: Beginner — use case đơn giản nhất, không cần graph hay verifier.

---

## Use Case

User nhắn tin với agent để quản lý todo list. Agent cần:
1. Nhớ các todo đã thêm trước đó (within session)
2. Trả lời câu hỏi về danh sách hiện tại
3. Mark item done khi user yêu cầu

---

## Architecture

```
User message
  └─→ TodoAgent._execute()
        ├─→ ContextAssembler.write()   # lưu message vào MemoryBackbone
        ├─→ ContextAssembler.assemble() # lấy context liên quan
        └─→ ILLMProvider.complete()    # gọi LLM với context
```

Không cần `IntentAnalyzer` hay `StrategySelector` — `DirectStrategy` đủ cho use case này.

---

## Wiring Code

```python
import anyio
from dataclasses import dataclass, field

from uaaf._testing.fakes import FakeLLMProvider
from uaaf.execution.agent import AgentResult, BaseAgent, Task
from uaaf.knowledge.context_assembler import ContextAssembler
from uaaf.knowledge.memory.backbone import MemoryBackbone
from uaaf.observability.audit import AuditLogger
from uaaf.observability.cost import Cost, CostPolicy, CostTracker
from uaaf.observability.rate_limit import RateLimiter, RatePolicy
from uaaf.observability.tracer import Tracer
from uaaf.providers.llm import CompletionRequest, Message
from uaaf.runtime.context import ContextScope, ExecutionContext


@dataclass
class TodoAgent(BaseAgent):
    llm: FakeLLMProvider = field(default_factory=FakeLLMProvider)
    assembler: ContextAssembler = field(
        default_factory=lambda: ContextAssembler(MemoryBackbone())
    )

    async def _execute(self, task: Task, context: ExecutionContext) -> AgentResult:
        user_message = str(task.payload.get("message", ""))
        scope_key = context.scope.session_id

        # 1. Ghi message vào memory
        await self.assembler.write(user_message, scope_key)

        # 2. Lấy context liên quan (recent + keyword-matched)
        assembled = await self.assembler.assemble(
            query=user_message,
            scope_key=scope_key,
            budget_tokens=1000,
        )

        # 3. Gọi LLM với context
        system_prompt = (
            "You are a helpful todo assistant.\n"
            f"Conversation history:\n{assembled.text}"
        )
        req = CompletionRequest(
            messages=[
                Message(role="system", content=system_prompt),
                Message(role="user", content=user_message),
            ],
            model="gpt-4o-mini",
        )
        response = await self.llm.complete(req)

        return AgentResult(
            task_id=task.task_id,
            output=response.content,
            cost=Cost(input_tokens=50, output_tokens=20, usd=0.0, provider="fake", model="fake"),
        )


async def demo() -> None:
    scope = ContextScope(user_id="u1", session_id="session-todo-1", domain="todo")
    ctx = ExecutionContext(scope=scope, correlation_id="c1")

    agent = TodoAgent(
        agent_id="todo-agent",
        cost_tracker=CostTracker(CostPolicy()),
        tracer=Tracer(),
        audit_logger=AuditLogger(),
        rate_limiter=RateLimiter(RatePolicy()),
    )

    for message in ["Add: buy milk", "Add: call dentist", "What's on my list?"]:
        result = await agent.execute(
            Task(task_id=f"t-{message[:5]}", payload={"message": message}),
            ctx,
        )
        print(f"User: {message}")
        print(f"Agent: {result.output}\n")


anyio.run(demo)
```

---

## Key Design Decisions

### Dùng `session_id` làm `scope_key`

`MemoryBackbone` phân tách memory theo `scope_key`. Dùng `session_id` → mỗi chat session có memory độc lập. Nếu cần persistence across sessions, dùng `user_id` thay.

### WorkingMemory vs EpisodicMemory

`MemoryBackbone` mặc định stack 2 layer:
- `WorkingMemoryStore` (max 50 entries, FIFO) — recent messages, luôn có trong context
- `EpisodicMemoryStore` (max 500 entries, keyword scoring) — long-term, chỉ recall khi relevant

Với todo app, cả hai đều hữu ích: working = recent turns, episodic = items added lâu hơn.

### Không dùng Verifier

Todo app trust = LOW (không ảnh hưởng tài chính/bảo mật). Bỏ qua verifier là hợp lý.
Nếu cần validate format (JSON checklist), thêm `SchemaVerifier`:

```python
from uaaf.cognitive.verifiers.schema import SchemaVerifier

verifier = SchemaVerifier(required_keys=["items", "done"], output_must_be_json=True)
```

---

## Cost Budget

```python
from uaaf.observability.cost import CostPolicy

policy = CostPolicy(
    per_user_per_day_usd=0.10,    # user không tiêu quá $0.10/ngày
    per_domain_per_month_usd=50.0,
    global_per_hour_usd=10.0,
)
tracker = CostTracker(policy)
```

`CostTracker` tự raise `BudgetExceededError` khi vượt ngưỡng — `BaseAgent` bắt và trả về `FatalError`.

---

## Production Checklist

- [ ] Thay `FakeLLMProvider` → `OpenAIProvider` hoặc `AnthropicProvider`
- [ ] Truyền `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` qua environment variable (không hardcode)
- [ ] Set `CostPolicy` phù hợp với user tier của bạn
- [ ] Nếu cần persist memory across restarts → implement `IMemoryStore` với PostgreSQL/Redis backend
- [ ] Add rate limit: `RatePolicy(requests_per_minute=20)` để tránh abuse
