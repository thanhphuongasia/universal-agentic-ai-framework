# Class-Based — `BaseAgent` (Advanced)

← [Quickstart Index](README.md) | [All guides](../)

> When Factory không cover: custom multi-step domain logic, custom strategies, custom verifier pipeline, override execution flow.

---

## 2. Class-Based — Advanced & Flexible

Cần khi factory không cover:
- Custom domain logic với multiple LLM calls trong 1 task
- Stateful agent với memory backbone custom
- Multi-agent orchestration (AgentPool + custom routing)
- Custom verifier pipeline trong evaluator strategy
- Override execution flow (caching, fallback chains, A/B test prompts)

### 2.1 Skeleton

```python
import anyio
from dataclasses import dataclass, field
from ryuu_execution.agent import BaseAgent, Task, AgentResult
from ryuu_core.models import Cost
from ryuu_providers.adapters.openai import OpenAIProvider
from ryuu_providers.llm import CompletionRequest, Message
from ryuu_observability.cost import CostTracker, CostPolicy
from ryuu_workflow.context import ContextScope, ExecutionContext


@dataclass
class CustomerServiceAgent(BaseAgent):
    llm: OpenAIProvider = field(default_factory=lambda: OpenAIProvider(api_key="sk-..."))

    async def _execute(self, task: Task, context: ExecutionContext) -> AgentResult:
        # Multi-step logic: classify intent → fetch data → generate reply
        intent = await self._classify(task.payload.get("message", ""))
        data = await self._fetch_context(intent, context)
        reply = await self._generate_reply(intent, data)

        return AgentResult(
            task_id=task.task_id,
            output=reply.content,
            cost=Cost(
                input_tokens=reply.usage.input_tokens,
                output_tokens=reply.usage.output_tokens,
                usd=0.001,
                provider="openai",
                model="gpt-4o-mini",
            ),
        )

    async def _classify(self, message: str):
        request = CompletionRequest(
            messages=[Message(role="user", content=message)],
            model="gpt-4o-mini",
        )
        return await self.llm.complete(request)

    async def _fetch_context(self, intent, ctx): ...
    async def _generate_reply(self, intent, data): ...


async def main():
    scope = ContextScope(user_id="customer-42", session_id="s1", domain="support")
    ctx = ExecutionContext(scope=scope, correlation_id="req-001")

    agent = CustomerServiceAgent(
        agent_id="support-agent",
        cost_tracker=CostTracker(CostPolicy(max_usd_per_session=1.0)),
    )

    result = await agent.execute(
        Task(task_id="t1", payload={"message": "Check my order status"}),
        ctx,
    )
    print(result.output)


anyio.run(main)
```

Cross-cutting (Tracer, AuditLogger, RateLimiter) optional — defaults là NullObject, framework không bắt buộc inject.

---

