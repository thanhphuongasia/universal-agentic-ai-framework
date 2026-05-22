# ryuu-providers-anthropic

Anthropic `ILLMProvider` adapter — wraps `anthropic.AsyncAnthropic`.

```python
from ryuu_providers_anthropic import AnthropicProvider

provider = AnthropicProvider(api_key=os.environ["ANTHROPIC_API_KEY"])
result = await provider.complete(request)
```

Implements the `ILLMProvider` Protocol from `ryuu-providers-core`. Maps Anthropic errors to RYUU error classes via `ryuu_core.errors.classify_external_error`.
