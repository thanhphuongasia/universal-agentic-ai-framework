# Batch Processing — `BatchRunner` (Phase 12 + 12.1)

← [Quickstart Index](README.md) | [All guides](../)

> Process N inputs through an Agent. Two modes: concurrent gather (real-time) hoặc OpenAI Batch API (50% discount, 24h SLA).

---

## 1. Khi Nào Dùng

- ✅ Dataset processing (≥ 100 items)
- ✅ Bulk text summarization / classification / extraction
- ✅ Eval suite runs (run cùng query với N variant prompts)
- ✅ Backfill historical data
- ❌ Real-time chat (dùng `.run()` hoặc `.stream()` thay)

## 2. Mode `gather` (Concurrent, Real-Time)

Concurrent execution via `anyio.create_task_group` + `Semaphore(max_concurrent)`. Same cost as N × `.run()`.

```python
from ryuu import Agent, BatchRunner

agent = Agent(model="gpt-4o-mini", instructions="Summarize in 1 sentence")

runner = BatchRunner(agent=agent, max_concurrent=10)

# Plain string inputs → returns list[AgentResult]
results = await runner.run([
    "Long text 1...",
    "Long text 2...",
    "Long text N...",
])

# Dict inputs với custom ID → returns list[BatchItem]
results = await runner.run([
    {"id": "doc-1", "input": "Long text 1..."},
    {"id": "doc-2", "input": "Long text 2..."},
])
# results[0].id == "doc-1"
# results[0].output == "..."
# results[0].cost_usd == 0.0001
```

**Params:**
- `max_concurrent: int = 10` — cap parallelism (Semaphore)
- `on_error: "raise" | "collect"` — first failure halts (default) hoặc continue (collect into `BatchItem.error`)

## 3. Mode `openai_batch` (50% Discount)

Real OpenAI Batch API: build JSONL → upload → create batch → poll status → download output → map back to input order.

```python
from ryuu import Agent, BatchRunner

agent = Agent(model="gpt-4o-mini", instructions="Summarize")
runner = BatchRunner(
    agent=agent,
    mode="openai_batch",
    poll_interval_s=30.0,       # check status every 30s
    completion_window="24h",     # OpenAI SLA window
)

# Returns list[BatchItem] always (in openai_batch mode)
results = await runner.run([
    {"id": f"doc-{i}", "input": text}
    for i, text in enumerate(large_corpus)
])
```

**Lợi ích:**
- **50% cost discount** so với standard API (input + output tokens đều rẻ một nửa)
- 24h SLA (usually < 1h actual)

**Khi nào dùng:** ≥ 100 inputs + tolerate 24h SLA.

## 4. Lifecycle (openai_batch)

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Build JSONL — 1 chat completion request per input        │
│    {"custom_id": "doc-1", "method": "POST",                 │
│     "url": "/v1/chat/completions", "body": {...}}           │
│ 2. Upload via Files API (purpose="batch") → input_file_id   │
│ 3. Create batch (endpoint, completion_window) → batch_id    │
│ 4. Poll status every `poll_interval_s` until terminal       │
│ 5. status=completed → download output_file                  │
│ 6. Parse JSONL → map custom_id back to input order          │
└─────────────────────────────────────────────────────────────┘
```

**Terminal states:** `completed` (success) / `failed` / `expired` / `cancelled` → 3 sau raise `RuntimeError`.

## 5. Error Handling

```python
# Mode A — raise on first failure (default)
runner = BatchRunner(agent=agent, on_error="raise")
try:
    results = await runner.run(inputs)
except Exception as exc:
    log.error(f"batch failed: {exc}")

# Mode B — collect, never raise
runner = BatchRunner(agent=agent, on_error="collect")
results = await runner.run(inputs)
for item in results:
    if item.error:
        log.warning(f"{item.id} failed: {item.error}")
    else:
        process(item.output)
```

**Line-level errors trong openai_batch** (e.g. per-input rate limit) → `BatchItem.error` set với code + message từ OpenAI response.

## 6. Custom `BatchAPIClient` (Testing)

For testing or custom batch backends, implement the `BatchAPIClient` protocol:

```python
from ryuu.batch import BatchAPIClient
from typing import Any

class MyBatchClient:
    async def upload_input_file(self, jsonl_bytes: bytes) -> str: ...
    async def create_batch(self, input_file_id: str, endpoint: str, completion_window: str) -> str: ...
    async def get_batch_status(self, batch_id: str) -> dict[str, Any]: ...
    async def download_file(self, file_id: str) -> str: ...

runner = BatchRunner(agent=agent, mode="openai_batch", batch_client=MyBatchClient())
```

Default: `OpenAIBatchClient()` (uses `AsyncOpenAI` SDK with `OPENAI_API_KEY` env).

## 7. Imports

```python
from ryuu import (
    BatchRunner,         # main runner
    BatchItem,           # result wrapper (id, output, error, cost_usd)
    BatchAPIClient,      # protocol for custom backends
    OpenAIBatchClient,   # default production client
)
```

## 8. Roadmap

| Mode | Status |
|---|---|
| `gather` — concurrent | ✅ Phase 12 |
| `openai_batch` — real API | ✅ Phase 12.1 |
| `anthropic_batch` — Message Batches API | 🔲 future |
| Cost tracking integration (record actual batch cost) | 🔲 future |
| Resumable batches (persist batch_id, resume after restart) | 🔲 future |
