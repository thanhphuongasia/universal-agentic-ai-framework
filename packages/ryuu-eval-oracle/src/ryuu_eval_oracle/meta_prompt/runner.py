"""Execute the meta-prompt against a ryuu provider and return the oracle prompt.

Uses `ryuu_providers_core.ILLMProvider` — the framework-wide LLM contract — so
this module does NOT introduce its own adapter type. Any provider (Anthropic,
OpenAI, custom) registered in ryuu_providers works here without further glue.
"""

from __future__ import annotations

from dataclasses import dataclass

from ryuu_providers_core import CompletionRequest, ILLMProvider, Message

from .builder import META_PROMPT_MODEL, META_PROMPT_VERSION, render_user_message


@dataclass(frozen=True)
class MetaGenerateResult:
    """Outcome of running the meta-prompt."""

    oracle_prompt: str
    meta_prompt_version: str
    model: str
    provider_id: str  # which provider produced this (e.g. "anthropic")


async def generate_oracle_prompt(
    provider: ILLMProvider,
    *,
    production_prompt_text: str,
    project_name: str = "",
    domain_hint: str = "",
    output_schema_hint: str = "",
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.0,
) -> MetaGenerateResult:
    """Run the meta-prompt → produce an oracle prompt string.

    Provider-neutral — pass any `ILLMProvider` (AnthropicProvider, OpenAIProvider,
    a fallback chain, etc). The returned `oracle_prompt` is the raw LLM output;
    UI is expected to render it in an editable textarea so a human can adjust
    before the oracle run.
    """
    chosen_model = model or META_PROMPT_MODEL
    user_text = render_user_message(
        production_prompt_text=production_prompt_text,
        project_name=project_name,
        domain_hint=domain_hint,
        output_schema_hint=output_schema_hint,
    )
    request = CompletionRequest(
        messages=[Message(role="user", content=user_text)],
        model=chosen_model,
        system=_SYSTEM_TEXT,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    response = await provider.complete(request)
    return MetaGenerateResult(
        oracle_prompt=(response.content or "").strip(),
        meta_prompt_version=META_PROMPT_VERSION,
        model=response.model or chosen_model,
        provider_id=getattr(provider, "provider_id", ""),
    )


# System text re-exported here to keep the import surface flat; sourced from
# builder so the YAML stays the single source of truth.
from .builder import _SYSTEM_TEXT  # noqa: E402  — intentional late import


__all__ = ["MetaGenerateResult", "generate_oracle_prompt"]
