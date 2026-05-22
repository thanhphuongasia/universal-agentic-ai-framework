"""ryuu-providers — convenience meta-package.

After Phase 8.12 the implementation lives in 3 sub-packages:
  • ryuu-providers-core       Protocols + types + pricing + middleware
  • ryuu-providers-openai     OpenAI adapter (optional)
  • ryuu-providers-anthropic  Anthropic adapter (optional)

This namespace re-exports the public API for back-compat. New code should
prefer:
    from ryuu_providers_core import ILLMProvider, CompletionRequest, ...
    from ryuu_providers_openai import OpenAIProvider
    from ryuu_providers_anthropic import AnthropicProvider

Old code continues to work:
    from ryuu_providers.llm import ILLMProvider              # ✓ shim
    from ryuu_providers.adapters.openai import OpenAIProvider  # ✓ shim
"""

from ryuu_providers_core import (
    CONTEXT_WINDOW,
    PRICING,
    CircuitBreaker,
    CircuitState,
    CompletionRequest,
    Embedding,
    ILLMProvider,
    Message,
    ModelRouter,
    ProviderFallbackChain,
    Response,
    StreamChunk,
    TokenUsage,
    calculate_usd,
    reload_pricing,
)

__all__ = [
    "ILLMProvider",
    "CompletionRequest",
    "Message",
    "Response",
    "StreamChunk",
    "TokenUsage",
    "Embedding",
    "CircuitBreaker",
    "CircuitState",
    "ProviderFallbackChain",
    "ModelRouter",
    "calculate_usd",
    "reload_pricing",
    "PRICING",
    "CONTEXT_WINDOW",
]
