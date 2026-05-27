"""Execute the meta-prompt against an LLM adapter and return the raw oracle prompt.

Provider-agnostic — caller injects an `adapter` that exposes
`async chat(messages, model=..., **kwargs) -> str` (returns the assistant text).

Keeping the protocol minimal lets the host project plug in whatever adapter
it already uses (e.g. ryuu-llm, anthropic SDK directly, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .builder import META_PROMPT_MODEL, META_PROMPT_VERSION, build_meta_messages


class ChatAdapter(Protocol):
    """Minimal async chat interface."""

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        **kwargs: Any,
    ) -> str: ...


@dataclass(frozen=True)
class MetaGenerateResult:
    """Outcome of running the meta-prompt."""

    oracle_prompt: str
    meta_prompt_version: str
    model: str
    raw_response: str  # same as oracle_prompt unless adapter wraps it


async def generate_oracle_prompt(
    adapter: ChatAdapter,
    *,
    production_prompt_text: str,
    project_name: str = "",
    domain_hint: str = "",
    model: str | None = None,
) -> MetaGenerateResult:
    """Run the meta-prompt → produce an oracle prompt string.

    The returned `oracle_prompt` is the raw LLM output; downstream UI is
    expected to render it in an editable textarea so the human can adjust
    before the oracle run.
    """
    chosen_model = model or META_PROMPT_MODEL
    messages = build_meta_messages(
        production_prompt_text=production_prompt_text,
        project_name=project_name,
        domain_hint=domain_hint,
    )
    response = await adapter.chat(messages, model=chosen_model)
    text = (response or "").strip()
    return MetaGenerateResult(
        oracle_prompt=text,
        meta_prompt_version=META_PROMPT_VERSION,
        model=chosen_model,
        raw_response=text,
    )


__all__ = ["ChatAdapter", "MetaGenerateResult", "generate_oracle_prompt"]
