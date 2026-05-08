# Adapter Guide — Thêm LLM Provider mới vào UAAF

Hướng dẫn implement `ILLMProvider` để kết nối bất kỳ LLM nào vào framework.

---

## 1. Contract — ILLMProvider

```python
# uaaf/providers/llm.py
class ILLMProvider(Protocol):
    async def complete(self, request: CompletionRequest) -> Response: ...
    async def embed(self, text: str, model: str | None = None) -> Embedding: ...
```

Adapter chỉ cần implement `complete()`. `embed()` có thể raise `NotImplementedError` nếu provider không hỗ trợ.

---

## 2. Input — CompletionRequest

```python
@dataclass
class CompletionRequest:
    messages: list[Message]          # lịch sử hội thoại
    model: str                       # tên model hoặc tier string ("cheap"/"powerful")
    temperature: float | None        # None = dùng default của provider
    max_tokens: int | None           # None = dùng default của provider
    tools: list[dict] | None         # OpenAI-format tool schemas, None = không dùng tool
    system: str | None               # system prompt riêng (một số provider tách ra)
    response_schema: dict | None     # JSON schema cho structured output

@dataclass
class Message:
    role: str                        # "user" | "assistant" | "tool" | "system"
    content: str
    tool_calls: list[dict] | None    # khi role="assistant" và model gọi tool
    tool_call_id: str | None         # khi role="tool" (kết quả tool)
```

---

## 3. Output — Response (quan trọng nhất)

```python
@dataclass
class Response:
    content: str                     # text model emit — CÓ THỂ RỖNG khi có tool_calls
    model: str
    usage: TokenUsage                # input_tokens + output_tokens
    finish_reason: str               # "stop" | "tool_calls" | "length" | "end_turn"
    metadata: dict                   # {"tool_calls": [...]} nếu model gọi tool
```

### Hai trường `react_loop` phụ thuộc vào

| Trường | Mô tả | Sai → hậu quả |
|---|---|---|
| `content` | Text model emit (thought) | Rỗng → `on_thought` không fire (ok, có fallback synthetic) |
| `metadata["tool_calls"]` | List tool calls — **phải đúng format** | Sai → react_loop không execute tool, trả final answer ngay |

### UAAF tool_calls format

```python
metadata["tool_calls"] = [
    {
        "id": "call_abc123",          # string ID, duy nhất trong response
        "function": {
            "name": "get_weather",    # tên tool
            "arguments": {            # dict Python (KHÔNG phải JSON string)
                "city": "Tokyo",
            },
        },
    },
    # ... thêm tool calls nếu model call nhiều tool cùng lúc
]
```

**Lưu ý**: OpenAI SDK trả `arguments` là JSON string — phải `json.loads()` trước khi map.

---

## 4. Error mapping — classify_external_error

Mọi exception từ SDK đều phải đi qua `classify_external_error`:

```python
from uaaf.observability.errors import classify_external_error

try:
    resp = await self._client.some_api_call(...)
except Exception as exc:
    raise classify_external_error(exc) from exc
```

Hàm này phân loại lỗi thành:

| UAAF Error | Trigger | Caller hành động |
|---|---|---|
| `RetryableError` | rate limit, timeout, 429/503 | retry với backoff |
| `DegradedError` | quota exceeded, service degraded | fallback sang provider khác |
| `FatalError` | auth error, invalid request, 400/401 | fail nhanh, không retry |

Nếu provider của bạn raise exception không thuộc các loại trên, `classify_external_error` wrap thành `RetryableError` theo mặc định.

---

## 5. Skeleton đầy đủ

```python
# uaaf/providers/adapters/my_provider.py
from __future__ import annotations

import json
from typing import Any

from uaaf.observability._pricing import calculate_usd
from uaaf.observability.cost import Cost
from uaaf.observability.errors import classify_external_error
from uaaf.providers.llm import (
    CompletionRequest,
    Embedding,
    Response,
    TokenUsage,
)

try:
    from my_sdk import AsyncMyClient
except ImportError:
    AsyncMyClient = None  # type: ignore[assignment,misc]


class MyProvider:
    provider_id = "my_provider"

    def __init__(self, api_key: str, default_model: str = "my-model-v1") -> None:
        if AsyncMyClient is None:
            raise ImportError('pip install "uaaf[my_provider]"')
        self._client = AsyncMyClient(api_key=api_key)
        self._default_model = default_model

    async def complete(self, request: CompletionRequest) -> Response:
        model = request.model or self._default_model

        # 1. Map CompletionRequest → SDK format
        sdk_messages = self._map_messages(request.messages)
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": sdk_messages,
        }
        if request.max_tokens:
            kwargs["max_tokens"] = request.max_tokens
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.tools:
            kwargs["tools"] = request.tools

        # 2. Call SDK
        try:
            resp = await self._client.chat((**kwargs))
        except Exception as exc:
            raise classify_external_error(exc) from exc

        # 3. Map response → UAAF types
        content_text = ""
        metadata: dict[str, Any] = {}
        tool_calls = []

        # Xử lý từng output block/choice
        for part in resp.output_parts:          # tên field phụ thuộc SDK
            if part.type == "text":
                content_text += part.text
            elif part.type == "tool_call":
                tool_calls.append({
                    "id": part.id,
                    "function": {
                        "name": part.name,
                        "arguments": part.arguments   # đảm bảo là dict
                        if isinstance(part.arguments, dict)
                        else json.loads(part.arguments),
                    },
                })

        if tool_calls:
            metadata["tool_calls"] = tool_calls

        return Response(
            content=content_text,
            model=model,
            usage=TokenUsage(
                input_tokens=resp.usage.input,
                output_tokens=resp.usage.output,
            ),
            finish_reason=resp.stop_reason or "stop",
            metadata=metadata,
        )

    def _map_messages(self, messages: list) -> list[dict]:
        result = []
        for m in messages:
            msg: dict[str, Any] = {"role": m.role, "content": m.content or ""}
            if m.tool_calls:
                msg["tool_calls"] = m.tool_calls
            if m.tool_call_id:
                msg["tool_call_id"] = m.tool_call_id
            result.append(msg)
        return result

    async def embed(self, text: str, model: str | None = None) -> Embedding:
        try:
            resp = await self._client.embed(text=text, model=model or "my-embed-model")
        except Exception as exc:
            raise classify_external_error(exc) from exc
        return Embedding(vector=resp.embedding, model=model or "my-embed-model")

    def estimate_cost(self, request: CompletionRequest) -> Cost:
        model = request.model or self._default_model
        input_est = sum(len(m.content.split()) * 4 // 3 for m in request.messages)
        output_est = request.max_tokens or 256
        return Cost(
            input_tokens=input_est,
            output_tokens=output_est,
            usd=calculate_usd(model, input_est, output_est),
            provider=self.provider_id,
            model=model,
        )

    async def close(self) -> None:
        await self._client.close()
```

---

## 6. Provider theo từng SDK — mapping cụ thể

### OpenAI SDK

```python
choice = resp.choices[0]

# content
content_text = choice.message.content or ""

# tool_calls — arguments là JSON string, phải parse
if choice.message.tool_calls:
    tool_calls = [
        {
            "id": tc.id,
            "function": {
                "name": tc.function.name,
                "arguments": json.loads(tc.function.arguments or "{}"),
            },
        }
        for tc in choice.message.tool_calls
    ]

# usage
input_tokens  = resp.usage.prompt_tokens
output_tokens = resp.usage.completion_tokens
finish_reason = choice.finish_reason or "stop"
```

### Anthropic SDK

```python
# resp.content là list of blocks — text và tool_use có thể xuất hiện cùng nhau
content_text = ""
tool_calls = []

for block in resp.content:
    if block.type == "text":
        content_text = block.text          # Claude thường emit thought ở đây
    elif block.type == "tool_use":
        tool_calls.append({
            "id": block.id,
            "function": {
                "name": block.name,
                "arguments": block.input,  # đã là dict, không cần parse
            },
        })

input_tokens  = resp.usage.input_tokens
output_tokens = resp.usage.output_tokens
finish_reason = resp.stop_reason or "end_turn"
```

> **Claude behavior**: Claude thường emit text thought trước khi call tool.
> `content_text` sẽ có nội dung → `on_thought` fire với text thật, không cần fallback synthetic.

### Gemini SDK (`google-generativeai`)

```python
# resp.parts là list, có thể chứa text và function_call
content_text = ""
tool_calls = []

for part in resp.parts:
    if hasattr(part, "text") and part.text:
        content_text += part.text
    elif hasattr(part, "function_call"):
        fc = part.function_call
        tool_calls.append({
            "id": f"gemini-{fc.name}-{id(fc)}",   # Gemini không có call ID
            "function": {
                "name": fc.name,
                "arguments": dict(fc.args),         # Struct → dict
            },
        })

input_tokens  = resp.usage_metadata.prompt_token_count
output_tokens = resp.usage_metadata.candidates_token_count
finish_reason = "stop"
```

### OpenAI-compatible APIs (Ollama, Groq, Together AI, LM Studio)

Không cần adapter mới — dùng `OpenAIProvider` với `base_url`:

```python
from uaaf.providers.adapters.openai import OpenAIProvider

# Ollama local
provider = OpenAIProvider(
    api_key="ollama",
    base_url="http://localhost:11434/v1",
    default_model="llama3.2",
)

# Groq
provider = OpenAIProvider(
    api_key=os.environ["GROQ_API_KEY"],
    base_url="https://api.groq.com/openai/v1",
    default_model="llama-3.3-70b-versatile",
)

# Together AI
provider = OpenAIProvider(
    api_key=os.environ["TOGETHER_API_KEY"],
    base_url="https://api.together.xyz/v1",
    default_model="meta-llama/Llama-3-70b-chat-hf",
)

# LM Studio
provider = OpenAIProvider(
    api_key="lm-studio",
    base_url="http://localhost:1234/v1",
    default_model="local-model",
)
```

---

## 7. Checklist trước khi dùng adapter trong production

```
[ ] complete() trả Response với content="" khi không có text (không phải None)
[ ] metadata["tool_calls"] đúng format — arguments là dict, không phải JSON string
[ ] Mọi SDK exception đi qua classify_external_error()
[ ] TokenUsage đúng (input + output riêng biệt, không cộng chung)
[ ] estimate_cost() dùng calculate_usd() từ pricing.yaml
[ ] close() gọi để release connection khi service shutdown
[ ] Thêm model vào pricing.yaml nếu chưa có
[ ] Viết test với FakeLLMProvider trước, dùng adapter thật sau
```

---

## 8. Test adapter mới

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uaaf.providers.llm import CompletionRequest, Message


@pytest.mark.anyio
async def test_my_provider_complete_no_tools():
    mock_resp = MagicMock()
    mock_resp.output_parts = [MagicMock(type="text", text="Hello!")]
    mock_resp.usage = MagicMock(input=10, output=5)
    mock_resp.stop_reason = "stop"

    with patch("my_sdk.AsyncMyClient") as MockClient:
        MockClient.return_value.chat = AsyncMock(return_value=mock_resp)
        from uaaf.providers.adapters.my_provider import MyProvider

        provider = MyProvider(api_key="test")
        req = CompletionRequest(
            messages=[Message(role="user", content="Hi")],
            model="my-model-v1",
        )
        resp = await provider.complete(req)

    assert resp.content == "Hello!"
    assert resp.usage.input_tokens == 10
    assert "tool_calls" not in resp.metadata


@pytest.mark.anyio
async def test_my_provider_complete_with_tool_call():
    mock_tc = MagicMock(type="tool_call", id="c1", name="search", arguments={"q": "uaaf"})
    mock_resp = MagicMock()
    mock_resp.output_parts = [mock_tc]
    mock_resp.usage = MagicMock(input=20, output=10)
    mock_resp.stop_reason = "tool_calls"

    with patch("my_sdk.AsyncMyClient") as MockClient:
        MockClient.return_value.chat = AsyncMock(return_value=mock_resp)
        from uaaf.providers.adapters.my_provider import MyProvider

        provider = MyProvider(api_key="test")
        req = CompletionRequest(
            messages=[Message(role="user", content="Search for uaaf")],
            model="my-model-v1",
        )
        resp = await provider.complete(req)

    assert resp.content == ""
    tc = resp.metadata["tool_calls"][0]
    assert tc["function"]["name"] == "search"
    assert tc["function"]["arguments"] == {"q": "uaaf"}   # dict, not string
    assert isinstance(tc["id"], str)
```
