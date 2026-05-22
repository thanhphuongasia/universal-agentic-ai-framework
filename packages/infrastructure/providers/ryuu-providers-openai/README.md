# ryuu-providers-openai

OpenAI `ILLMProvider` adapter — wraps `openai.AsyncOpenAI`.

```python
from ryuu_providers_openai import OpenAIProvider

provider = OpenAIProvider(api_key=os.environ["OPENAI_API_KEY"])
result = await provider.complete(request)
```

Implements the `ILLMProvider` Protocol from `ryuu-providers-core`. Maps OpenAI errors to RYUU error classes via `ryuu_core.errors.classify_external_error`.
