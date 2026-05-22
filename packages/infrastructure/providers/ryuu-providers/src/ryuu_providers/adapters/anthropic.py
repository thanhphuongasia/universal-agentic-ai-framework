"""Back-compat shim. Canonical source: `ryuu_providers_anthropic.provider`.

Requires `ryuu-providers-anthropic` to be installed:
    pip install ryuu-providers[anthropic]    # via extras
    pip install ryuu-providers-anthropic      # directly
"""

try:
    from ryuu_providers_anthropic.provider import AnthropicProvider
except ImportError as e:
    raise ImportError(
        "AnthropicProvider requires `ryuu-providers-anthropic`. "
        "Install with: pip install 'ryuu-providers[anthropic]' or pip install ryuu-providers-anthropic"
    ) from e

__all__ = ["AnthropicProvider"]
