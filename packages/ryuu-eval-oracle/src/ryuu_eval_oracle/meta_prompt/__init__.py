"""Generic oracle meta-prompt subsystem.

Public API:
    META_PROMPT_VERSION       — version string read from system.yaml
    META_PROMPT_MODEL         — default LLM model (e.g. claude-opus-4-7)
    build_meta_messages(...)  — produce provider-neutral [{role, content}] list
    render_user_message(...)  — just the user message text, if needed alone
    generate_oracle_prompt(...) — async helper running the meta-prompt via
                                  a supplied ChatAdapter
    ChatAdapter               — Protocol describing the adapter contract
    MetaGenerateResult        — dataclass returned by generate_oracle_prompt
"""

from .builder import (
    META_PROMPT_MODEL,
    META_PROMPT_VERSION,
    build_meta_messages,
    render_user_message,
)
from .runner import ChatAdapter, MetaGenerateResult, generate_oracle_prompt

__all__ = [
    "META_PROMPT_MODEL",
    "META_PROMPT_VERSION",
    "build_meta_messages",
    "render_user_message",
    "ChatAdapter",
    "MetaGenerateResult",
    "generate_oracle_prompt",
]
