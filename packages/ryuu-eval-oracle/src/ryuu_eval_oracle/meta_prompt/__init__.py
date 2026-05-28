"""Generic oracle meta-prompt subsystem.

Public API:
    META_PROMPT_VERSION       — version string read from system.yaml
    META_PROMPT_MODEL         — default LLM model (e.g. claude-opus-4-7)
    build_meta_messages(...)  — produce provider-neutral [{role, content}] list
    render_user_message(...)  — just the user message text, if needed alone
    generate_oracle_prompt(...) — async helper that runs the meta-prompt via a
                                  `ryuu_providers_core.ILLMProvider`
    MetaGenerateResult        — dataclass returned by generate_oracle_prompt

Note: this module does not define its own adapter type. The framework-wide
contract is `ryuu_providers_core.ILLMProvider`; any provider that implements
it (AnthropicProvider, OpenAIProvider, ProviderFallbackChain, …) works here.
"""

from .builder import (
    META_PROMPT_MODEL,
    META_PROMPT_VERSION,
    build_meta_messages,
    render_user_message,
)
from .runner import MetaGenerateResult, generate_oracle_prompt

__all__ = [
    "META_PROMPT_MODEL",
    "META_PROMPT_VERSION",
    "build_meta_messages",
    "render_user_message",
    "MetaGenerateResult",
    "generate_oracle_prompt",
]
