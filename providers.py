"""Central LLM provider registry — one place to configure every model used.

Any module that needs to talk to an LLM gets its provider from `make_providers()`
instead of importing `AnthropicProvider` / `OpenAIProvider` directly and building
its own instance. This keeps:

  - API key wiring in ONE place (env vars read here)
  - Model defaults in ONE place
  - Provider singletons shared (circuit breakers / rate limiters stay coherent)

Usage:

    from providers import make_providers
    PROVIDERS = make_providers()
    build_eval_router(
        ...,
        llm_providers=PROVIDERS,
        oracle_strategy_factory=lambda: CrudMatrixOracleStrategy(
            provider=PROVIDERS["anthropic"],
        ),
    )
"""

from __future__ import annotations

import os
from typing import Any


def make_providers() -> dict[str, Any]:
    """Return {provider_key: ILLMProvider} from env config.

    Each provider is constructed only if its API key is present. Missing keys
    silently skip the provider so dev environments without every key still boot.
    """
    providers: dict[str, Any] = {}

    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            from ryuu_providers_anthropic import AnthropicProvider
            providers["anthropic"] = AnthropicProvider(
                default_model=os.environ.get(
                    "ANTHROPIC_DEFAULT_MODEL", "claude-opus-4-7",
                ),
            )
        except ImportError:
            pass

    if os.environ.get("OPENAI_API_KEY"):
        try:
            from ryuu_providers_openai import OpenAIProvider
            providers["openai"] = OpenAIProvider(
                default_model=os.environ.get(
                    "OPENAI_DEFAULT_MODEL", "gpt-4o",
                ),
            )
        except ImportError:
            pass

    return providers


__all__ = ["make_providers"]
