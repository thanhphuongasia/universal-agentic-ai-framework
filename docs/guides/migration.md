# Migration Guide — Strangler Pattern

> Cách migrate từ legacy AI code sang UAAF mà không big-bang rewrite.

---

## Nguyên tắc

1. **Strangler Fig pattern** — chạy UAAF song song legacy, không thay thế ngay
2. **Feature flag** — `USE_UAAF=true` để switch từng request sang UAAF path
3. **Metric equivalence** — verify output quality tương đương trước khi tắt legacy
4. **Rollback < 5 phút** — flip flag, không cần deploy

---

## Phase 1: Cài đặt và Feature Flag

### Install UAAF vào project hiện tại

```bash
pip install "uaaf[openai]"
```

### Thêm feature flag

```python
import os

USE_UAAF = os.getenv("USE_UAAF", "false").lower() == "true"
```

### Router pattern

```python
async def process_request(user_input: str, context: dict) -> str:
    if USE_UAAF:
        return await uaaf_handler(user_input, context)
    return await legacy_handler(user_input, context)
```

---

## Phase 2: Shadow Mode (chạy cả hai, so sánh output)

Trước khi commit sang UAAF path, chạy cả hai và compare. Không trả kết quả UAAF cho user — chỉ log để analyze:

```python
import asyncio
import logging

logger = logging.getLogger(__name__)


async def shadow_mode(user_input: str, context: dict) -> str:
    # Chạy song song, lấy kết quả legacy cho user
    legacy_result, uaaf_result = await asyncio.gather(
        legacy_handler(user_input, context),
        uaaf_handler(user_input, context),
        return_exceptions=True,
    )

    # Log để compare (không expose uaaf_result cho user)
    if not isinstance(uaaf_result, Exception):
        logger.info(
            "shadow_comparison",
            extra={
                "legacy_output": legacy_result,
                "uaaf_output": uaaf_result,
                "input_hash": hash(user_input),
            },
        )

    return str(legacy_result)  # vẫn dùng legacy
```

---

## Phase 3: Canary Release (5% traffic)

Khi shadow mode cho thấy UAAF output tương đương:

```python
import random


def should_use_uaaf(user_id: str, canary_percent: int = 5) -> bool:
    if not USE_UAAF:
        return False
    # Deterministic per user (không flicker giữa requests)
    return (hash(user_id) % 100) < canary_percent


async def process_request(user_input: str, user_id: str, context: dict) -> str:
    if should_use_uaaf(user_id):
        return await uaaf_handler(user_input, context)
    return await legacy_handler(user_input, context)
```

Tăng dần: 5% → 25% → 50% → 100%. Monitor error rate và latency ở mỗi bước.

---

## Phase 4: Full Cutover

Khi 100% traffic đã stable trên UAAF ≥ 1 tuần:

```bash
# Tắt legacy path
USE_UAAF=true
# Sau đó xóa legacy code trong sprint tiếp theo
```

---

## Migrate từng Component

### 1. Migrate LLM calls trước

**Before** (direct SDK call):
```python
import openai

client = openai.AsyncOpenAI()

async def call_llm(prompt: str) -> str:
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content
```

**After** (qua ILLMProvider):
```python
from uaaf.providers.adapters.openai import OpenAIProvider
from uaaf.providers.llm import CompletionRequest, Message

provider = OpenAIProvider(api_key=os.environ["OPENAI_API_KEY"])


async def call_llm(prompt: str) -> str:
    req = CompletionRequest(
        messages=[Message(role="user", content=prompt)],
        model="gpt-4o-mini",
    )
    response = await provider.complete(req)
    return response.content
```

Lợi ích ngay: cost tracking, circuit breaker, retry logic.

### 2. Migrate error handling

**Before**:
```python
async def handle_before(prompt: str) -> str:
    try:
        result = await call_llm(prompt)
        return result
    except Exception:
        return "Sorry, something went wrong"
```

**After**:
```python
from uaaf.observability.errors import DegradedError, RetryableError, retry_policy

async def call_with_retry(prompt: str) -> str:
    async for attempt in retry_policy(max_attempts=3):
        async with attempt:
            return await call_llm(prompt)
    raise DegradedError("LLM unavailable after retries")
```

### 3. Migrate memory/context

**Before** (custom dict in session):
```python
session_memory: dict[str, list[str]] = {}

def remember(session_id: str, text: str) -> None:
    session_memory.setdefault(session_id, []).append(text)
```

**After** (`MemoryBackbone`):
```python
from uaaf.knowledge.context_assembler import ContextAssembler
from uaaf.knowledge.memory.backbone import MemoryBackbone

assembler = ContextAssembler(MemoryBackbone())


async def remember(session_id: str, text: str) -> None:
    await assembler.write(observation=text, scope_key=session_id)
```

---

## Rollback Plan

Rollback < 5 phút — chỉ cần flip env var:

```bash
# Emergency rollback
USE_UAAF=false

# Hoặc nếu dùng Kubernetes / ECS
kubectl set env deployment/my-service USE_UAAF=false
# hoặc
aws ecs update-service --environment name=USE_UAAF,value=false
```

Không cần redeploy, không downtime.

---

## Metric Equivalence Checklist

Trước khi tắt legacy path, verify các metric sau tương đương (±10%):

| Metric | Cách measure |
|---|---|
| Response quality (user rating) | A/B test, collect thumbs up/down |
| Latency (P50, P95) | Compare in monitoring dashboard |
| Error rate | `DegradedError` count vs legacy exception rate |
| Cost per request | `CostTracker` vs manual estimation |
| Token usage | Log `TokenUsage` từ `Response` object |

---

## Common Pitfalls

### Pitfall 1: Import SDK trực tiếp trong domain code

```python
# WRONG — bypass circuit breaker, cost tracking, retry
import anthropic
client = anthropic.Anthropic()

# RIGHT — luôn qua ILLMProvider
from uaaf.providers.adapters.anthropic import AnthropicProvider
```

### Pitfall 2: Skip verifier "cho nhanh"

```python
async def wrong_pattern() -> None:
    # WRONG — raw LLM output không được trust trong high-stakes decisions
    signal = await llm.complete(req)
    execute_trade(signal.content)  # nguy hiểm!

async def right_pattern() -> None:
    # RIGHT
    verification = await verifier.verify(signal.content, ctx)
    if verification.passed:
        execute_trade(signal.content)
```

### Pitfall 3: Custom agent class không extend BaseAgent

```python
# WRONG — bypass cross-cutting (cost, trace, audit, rate limit)
class MyAgent:
    async def run(self, prompt): ...

# RIGHT
from uaaf.execution.agent import BaseAgent
class MyAgent(BaseAgent):
    async def _execute(self, task, context): ...
```
