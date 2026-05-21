"""Parse model string → ILLMProvider instance.

Supports formats:
    "gpt-4o"                          → OpenAIProvider (auto-detect)
    "o1-preview" / "o3-mini"          → OpenAIProvider (auto-detect)
    "claude-sonnet-4"                 → AnthropicProvider (auto-detect)
    "openai:gpt-4o"                   → OpenAIProvider (explicit)
    "anthropic:claude-haiku-4-5"      → AnthropicProvider (explicit)

Unknown model without explicit prefix → ValueError.
"""

from __future__ import annotations

import os

from ryuu_providers.llm import ILLMProvider

_OPENAI_PREFIXES: tuple[str, ...] = ("gpt-", "o1-", "o3-", "o4-")
_ANTHROPIC_PREFIXES: tuple[str, ...] = ("claude-",)


def build_provider(model: str, api_key: str | None = None) -> ILLMProvider:
    """Return ILLMProvider instance for the given model string.

    Args:
        model: Either bare model name (`gpt-4o`) or prefixed (`openai:gpt-4o`).
        api_key: Explicit API key. If None, falls back to env var
            (OPENAI_API_KEY or ANTHROPIC_API_KEY).

    Raises:
        ValueError: Model name cannot be mapped to a known provider.
    """
    if ":" in model:
        provider_name, _ = model.split(":", 1)
    elif model.startswith(_OPENAI_PREFIXES):
        provider_name = "openai"
    elif model.startswith(_ANTHROPIC_PREFIXES):
        provider_name = "anthropic"
    else:
        raise ValueError(
            f"Cannot auto-detect provider for model: {model!r}. "
            f"Use explicit prefix like 'openai:{model}' or 'anthropic:{model}'."
        )

    if provider_name == "openai":
        from ryuu_providers.adapters.openai import OpenAIProvider

        return OpenAIProvider(api_key=api_key or os.getenv("OPENAI_API_KEY", ""))

    if provider_name == "anthropic":
        from ryuu_providers.adapters.anthropic import AnthropicProvider

        return AnthropicProvider(api_key=api_key or os.getenv("ANTHROPIC_API_KEY", ""))

    raise ValueError(f"Unknown provider: {provider_name!r}")
