"""ryuu-providers-core — LLM provider Protocols + types + middleware.

Canonical home for:
  • ILLMProvider Protocol + value types (CompletionRequest, Message, Response, …)
  • Pricing tables (PRICING, CONTEXT_WINDOW, calculate_usd) — loaded from pricing.yaml
  • Provider middleware: CircuitBreaker, ModelRouter, ProviderFallbackChain

Concrete adapters ship as separate packages:
  • ryuu-providers-openai      OpenAIProvider
  • ryuu-providers-anthropic   AnthropicProvider
"""

from ryuu_providers_core._pricing import (
    CONTEXT_WINDOW,
    PRICING,
    calculate_usd,
    reload_pricing,
)
from ryuu_providers_core.circuit_breaker import CircuitBreaker, CircuitState
from ryuu_providers_core.fallback import ProviderFallbackChain
from ryuu_providers_core.llm import (
    CompletionRequest,
    Embedding,
    ILLMProvider,
    Message,
    Response,
    StreamChunk,
    TokenUsage,
)
from ryuu_providers_core.router import ModelRouter

__version__ = "0.3.0a1"

__all__ = [
    # llm
    "ILLMProvider",
    "CompletionRequest",
    "Message",
    "Response",
    "StreamChunk",
    "TokenUsage",
    "Embedding",
    # circuit_breaker
    "CircuitBreaker",
    "CircuitState",
    # fallback
    "ProviderFallbackChain",
    # router
    "ModelRouter",
    # pricing
    "calculate_usd",
    "reload_pricing",
    "PRICING",
    "CONTEXT_WINDOW",
]
