# Runbook — RYUU Operations

Hướng dẫn vận hành cho các tình huống phổ biến: thêm model, cập nhật giá, thêm tool, debug, rollback.

> Thêm provider mới (Gemini, Ollama, Groq, ...): xem [Adapter Guide](adapter-guide.md)

---

## 1. Thêm / cập nhật model pricing

**Không cần redeploy** — chỉ edit `pricing.yaml` ở root project.

### Bước

```bash
# 1. Edit pricing.yaml
vim pricing.yaml
```

```yaml
pricing:
  gpt-4o:          [2.50, 10.00]   # [USD/1M input, USD/1M output]
  my-new-model:    [1.50,  6.00]   # THÊM MỚI
context_window:
  gpt-4o:          128000
  my-new-model:    200000           # THÊM MỚI
```

```python
# 2. Reload trong long-running service (không cần restart)
from ryuu.observability._pricing import reload_pricing
reload_pricing()

# Hoặc reload từ custom path
reload_pricing(path=Path("/etc/ryuu/pricing.yaml"))
```

### Verify

```python
from ryuu.observability._pricing import PRICING, CONTEXT_WINDOW, calculate_usd

assert "my-new-model" in PRICING
cost = calculate_usd("my-new-model", 100_000, 50_000)  # input=100k, output=50k tokens
print(f"Cost: ${cost:.4f}")
```

### Override via env var (production)

```bash
RYUU_PRICING_FILE=/etc/ryuu/custom_pricing.yaml python -m myapp
```

---

## 2. Thêm tool vào ToolRegistry

### Bare async function (đơn giản)

```python
from ryuu.execution.tool_registry import ToolRegistry

registry = ToolRegistry()

async def search_web(query: str, max_results: int = 5, **kwargs) -> str:
    # ... implementation
    return json.dumps(results)

registry.register(
    "search_web",
    search_web,
    allowed_domains={"research", "general"},   # None = unrestricted
)
```

### ITool class (với schema)

```python
from ryuu.execution.tool_registry import ITool
from typing import Any

class SearchTool:
    tool_id = "search_web"
    schema = {
        "name": "search_web",
        "description": "Search the web for information",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    }

    async def execute(self, args: dict[str, Any]) -> Any:
        return await do_search(args["query"], args.get("max_results", 5))

registry.register("search_web", SearchTool(), allowed_domains={"research"})
```

### Verify domain restriction

```python
import asyncio

async def verify_domain_restriction():
    # finance domain — OK
    await registry.run({"id": "c1", "function": {"name": "buy_stock", "arguments": {}}}, domain="finance")

    # wrong domain — raises PermissionError
    try:
        await registry.run(..., domain="chat")
    except PermissionError as e:
        print(e)  # Tool 'buy_stock' not allowed in domain 'chat'

asyncio.run(verify_domain_restriction())
```

---

## 3. Thêm LLM provider mới

Implement `ILLMProvider` Protocol:

```python
from ryuu.providers.llm import ILLMProvider, CompletionRequest, Response, TokenUsage, Embedding


class MyCustomProvider:
    async def complete(self, request: CompletionRequest) -> Response:
        # call your LLM API
        raw = await my_llm_api.chat(
            model=request.model,
            messages=[{"role": m.role, "content": m.content} for m in request.messages],
        )
        return Response(
            content=raw.text,
            model=request.model,
            usage=TokenUsage(input_tokens=raw.input_tokens, output_tokens=raw.output_tokens),
            finish_reason=raw.stop_reason,
            metadata={},
        )

    async def embed(self, texts: list[str]) -> list[Embedding]:
        raise NotImplementedError
```

Inject vào agent như mọi provider khác.

---

## 4. Điều chỉnh CostPolicy (budget)

```python
from ryuu.observability.cost import CostPolicy, CostTracker

# Tight budget cho demo
tracker = CostTracker(CostPolicy(
    max_usd_per_session=0.10,   # 10 cents per session
    max_usd_per_day=5.00,
    max_usd_global=100.00,
))

# Production
tracker = CostTracker(CostPolicy(
    max_usd_per_session=2.00,
    max_usd_per_day=500.00,
    max_usd_global=10_000.00,
))
```

`CostTracker.enforce()` raise `DegradedError` nếu vượt budget. `BaseAgent` catch và re-raise — caller quyết định retry hay fail.

---

## 5. Điều chỉnh RatePolicy

```python
from ryuu.observability.rate_limit import RateLimiter, RatePolicy

# 10 requests/second, burst up to 50
limiter = RateLimiter(RatePolicy(rps=10.0, burst=50))

# Conservative — 1 req/sec, no burst
limiter = RateLimiter(RatePolicy(rps=1.0, burst=1))
```

Rate limit áp dụng per `scope_key` (= `user_id:session_id:domain`). Các user khác nhau không ảnh hưởng lẫn nhau.

---

## 6. Debug react_loop

### Xem từng bước Thought/Action/Observation

```python
from ryuu.execution.llm_agent import PrintCallbacks

# text, usage = await agent.react_loop(request, callbacks=PrintCallbacks())
# Output:
#   💭 Thought: I need to check the weather...
#   🔧 Action:  get_weather({"city": "Tokyo"})
#   📋 Observation: Weather in Tokyo: 28°C, sunny
#   ✅ Final answer: The weather in Tokyo is 28°C and sunny.
```

### Custom callbacks (ghi log thay vì print)

```python
import logging

logger = logging.getLogger("react")

class LogCallbacks:
    async def on_thought(self, text): logger.debug("thought: %s", text[:100])
    async def on_action(self, name, args): logger.info("action: %s %s", name, args)
    async def on_observation(self, name, result): logger.info("obs: %s -> %s", name, result[:50])
    async def on_final(self, text): logger.info("final: %s", text[:100])

# text, usage = await agent.react_loop(request, callbacks=LogCallbacks())
```

### Tăng max_rounds khi agent bị cut off

```python
# Default max_rounds=3 — tăng cho complex multi-step tasks
# text, usage = await agent.react_loop(request, max_rounds=8)
```

---

## 7. Token budget summary

```python
# text, usage = await agent.react_loop(request)
# summary = agent.budget_summary(usage, model="gpt-4o")

# print(f"Input:  {summary.input_tokens:,} tokens")
# print(f"Output: {summary.output_tokens:,} tokens")
# print(f"Total:  {summary.total_tokens:,} / {summary.window_size:,} ({summary.pct_used:.1f}% used)")
```

---

## 8. Đọc audit log

Audit log ghi theo JSONL với SHA-256 chain hash:

```bash
# Xem log của session cụ thể
grep '"session_id": "s1"' audit.jsonl | jq .

# Verify chain integrity (hash chain không bị tamper)
python -c "
import json, hashlib
prev = ''
for line in open('audit.jsonl'):
    ev = json.loads(line)
    expected = hashlib.sha256((prev + line.rstrip()).encode()).hexdigest()[:16]
    assert ev.get('hash', '') == expected, f'Chain broken at {ev[\"ts\"]}'
    prev = ev.get('hash', '')
print('Chain OK')
"
```

---

## 9. Thêm KnowledgeBackbone vào agent

```python
from ryuu.knowledge.context_assembler import ContextAssembler
from ryuu.knowledge.memory.backbone import MemoryBackbone

assembler = ContextAssembler(MemoryBackbone())

# Trong _execute():
async def _execute(self, task, context):
    # Lấy context liên quan
    kb_ctx = await assembler.assemble(
        query=str(task.payload["query"]),
        scope_key=context.scope.scope_key,
        budget_tokens=1000,
    )

    # Inject vào system prompt
    system_msg = f"Context:\n{kb_ctx.text}\n\nAnswer the user."
    req = CompletionRequest(
        messages=[
            Message(role="system", content=system_msg),
            Message(role="user", content=str(task.payload["query"])),
        ],
        model="gpt-4o",
    )
    text, usage = await self.react_loop(req)

    # Ghi lại observation để dùng sau
    await assembler.write(f"Q: {task.payload['query']} A: {text}", context.scope.scope_key)

    return AgentResult(task_id=task.task_id, output=text, cost=Cost.zero("openai", "gpt-4o"))
```

---

## 10. Checklist trước khi ship

```
[ ] pricing.yaml có đủ model sẽ dùng trong production
[ ] CostPolicy set budget phù hợp (không dùng default unlimited)
[ ] RatePolicy đủ cho expected QPS
[ ] AuditLogger backend="file" với path có write permission
[ ] Tất cả tools register đúng allowed_domains
[ ] max_rounds đặt hợp lý (3 cho simple, 6+ cho complex)
[ ] test suite xanh: pytest tests/ -q
[ ] type check: mypy ryuu/
[ ] lint: ruff check ryuu/
```

---

## 12. Wire RequestHandler cho conversational app

Dùng khi: app nhận free-text từ user và cần **tự động chọn strategy** dựa trên intent, thay vì hard-code `agent.execute()`.

### Kiến trúc

```
message
  → IIntentAnalyzer.analyze()      classify: intent_type / complexity / prompt
  → StrategySelector.select()      pick strategy dựa trên StructuredIntent
  → ctx_routed                     stamp strategy_id (immutable copy)
  → ICognitiveStrategy.execute()   translate intent → Task, dispatch qua pool
  → AgentPool.dispatch()           route đến agent đã register
  → CognitiveResult                content + strategy_id (routing proof)
```

### Bước 1 — Implement IIntentAnalyzer

```python
from dataclasses import dataclass
from ryuu.intent.models import DIRECT, ComplexityLevel, ModelTier, StructuredIntent

@dataclass
class MyIntentAnalyzer:
    async def analyze(self, message: str, scope_key: str, history=None) -> StructuredIntent:
        msg = message.lower()
        if "report" in msg or "breakdown" in msg:
            return StructuredIntent(
                intent_type="report",
                action=message,
                entities={"prompt_name": "report"},
                complexity=ComplexityLevel.LOW,
                confidence=0.9,
                suggested_strategy=DIRECT,
                suggested_model_tier=ModelTier.CHEAP,
            )
        # default
        return StructuredIntent(
            intent_type="query",
            action=message,
            entities={"prompt_name": "analyze"},
            complexity=ComplexityLevel.MEDIUM,
            confidence=0.8,
            suggested_strategy=DIRECT,
            suggested_model_tier=ModelTier.STANDARD,
        )
```

### Bước 2 — Implement domain ICognitiveStrategy

Domain strategy cần bridge `StructuredIntent` → `Task` payload hiểu được bởi agent.

```python
from ryuu.cognitive.strategy import IAgentPool, IVerifier
from ryuu.execution.agent import Task
from ryuu.execution.pool import AgentPool
from ryuu.intent.models import DIRECT, CognitiveResult, CostEstimate, StructuredIntent
from ryuu_workflow.context import ExecutionContext

class MyDirectStrategy:
    strategy_id = DIRECT

    def applicable(self, intent: StructuredIntent, context: ExecutionContext) -> bool:
        return True  # handles all intents; add checks to restrict

    def estimate_cost(self, intent, context) -> CostEstimate:
        return CostEstimate(input_tokens_est=1000, output_tokens_est=200, usd_est=0.0001)

    async def execute(self, intent, context, agent_pool: IAgentPool, verifier: IVerifier) -> CognitiveResult:
        task = Task(
            task_id=f"req-{context.correlation_id}",
            payload={
                "query": intent.action,
                "prompt": intent.entities.get("prompt_name", "analyze"),
            },
        )
        # Pass context so agent receives strategy_id (routing proof)
        if isinstance(agent_pool, AgentPool):
            result = await agent_pool.dispatch(task, context)
        else:
            result = await agent_pool.dispatch(task)
        return CognitiveResult(content=str(result.output), confidence=0.9, strategy_id=DIRECT)
```

### Bước 3 — Wire RequestHandler

```python
from ryuu._testing.fakes import FakeVerifier   # hoặc domain verifier thật
from ryuu.execution.pool import AgentPool
from ryuu.intent.selector import StrategySelector
from ryuu.runtime.request_handler import RequestHandler

pool = AgentPool()
pool.register(my_agent)   # agent đã build + ingest data

handler = RequestHandler(
    analyzer=MyIntentAnalyzer(),
    selector=StrategySelector([MyDirectStrategy()]),
    pool=pool,
    verifier=FakeVerifier(),
)
```

### Bước 4 — Handle request

```python
from ryuu_workflow.context import ContextScope, ExecutionContext

ctx = ExecutionContext(
    scope=ContextScope(user_id="u1", session_id="s1", domain="my-app"),
    correlation_id="req-001",
)

# result = await handler.handle("Give me a report of completed tasks", ctx)
# print(result.content)        # LLM output
# print(result.strategy_id)    # "direct" — routing proof
```

### So sánh với direct agent.execute()

| | `agent.execute()` | `RequestHandler.handle()` |
|---|---|---|
| prompt_name | caller chọn thủ công | analyzer tự động chọn |
| `ctx.strategy_id` | `None` | `"direct"` (routing proof) |
| intent classification | không có | `StructuredIntent` với type + complexity |
| swap strategy | sửa code caller | swap trong `StrategySelector` only |
| audit trail | không có strategy context | strategy_id xuất hiện trong audit log |

### Xem ví dụ thực tế

```bash
python -m examples.todo_app.main    # chạy cả direct + RequestHandler, có comparison table
```

---

## 11. Môi trường biến cần thiết

| Variable | Required | Default | Mô tả |
|---|---|---|---|
| `OPENAI_API_KEY` | Nếu dùng OpenAI | — | OpenAI API key |
| `ANTHROPIC_API_KEY` | Nếu dùng Anthropic | — | Anthropic API key |
| `RYUU_PRICING_FILE` | Không | `pricing.yaml` ở project root | Override pricing config |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Không | — | OpenTelemetry collector endpoint |
