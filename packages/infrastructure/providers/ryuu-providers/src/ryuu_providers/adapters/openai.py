"""Back-compat shim. Canonical source: `ryuu_providers_openai.provider`.

Requires `ryuu-providers-openai` to be installed:
    pip install ryuu-providers[openai]    # via extras
    pip install ryuu-providers-openai      # directly
"""

try:
    from ryuu_providers_openai.provider import OpenAIProvider, _supports_strict_schema
except ImportError as e:
    raise ImportError(
        "OpenAIProvider requires `ryuu-providers-openai`. "
        "Install with: pip install 'ryuu-providers[openai]' or pip install ryuu-providers-openai"
    ) from e

__all__ = ["OpenAIProvider", "_supports_strict_schema"]
