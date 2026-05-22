"""Conversation compaction — shrink long history without losing meaning.

When a conversation runs past ~80% of the model's context window, raw history
turns become a risk. Options:
  1. Drop oldest — loses early context (default behavior of `Session`).
  2. Compact — LLM summarizes old turns into one or more dense summary turns.

This module provides option (2). Compaction primitives:

  • IConversationCompactor — Protocol every compactor implements
  • LLMCompactor          — calls an LLM to produce a summary
  • HierarchicalCompactor — multi-level: compact → re-compact summaries → …

Wires through `ILLMProvider` (from ryuu-providers) and `PromptRegistry`
(from ryuu-prompts). The prompt template lives in
`ryuu_cognitive/prompts/compaction/v1.yaml` — edit YAML to tune without
redeploying code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ryuu_prompts import PromptRegistry
from ryuu_providers.llm import ILLMProvider


# ---------------------------------------------------------------------------
# Value types — minimal, format-agnostic. Consumers convert from their own
# Turn types (e.g. ryuu_messaging_core.Turn) at the boundary.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CompactionTurn:
    """A turn in the compactor's vocabulary. Maps cleanly from any chat format."""
    role: str   # "user" | "assistant" | "system" | "summary"
    text: str

    @classmethod
    def from_obj(cls, obj: Any) -> "CompactionTurn":
        """Best-effort conversion from any object with .role and .text/.content."""
        role = getattr(obj, "role", None) or obj.get("role", "user")  # type: ignore[union-attr]
        text = (
            getattr(obj, "text", None)
            or getattr(obj, "content", None)
            or obj.get("text", "")           # type: ignore[union-attr]
            or obj.get("content", "")        # type: ignore[union-attr]
        )
        return cls(role=role, text=text)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class IConversationCompactor(Protocol):
    """Strategy for shrinking long conversation history."""

    threshold_tokens: int     # compact when total ≥ this
    keep_recent_turns: int    # always preserve the last N raw turns

    async def needs_compaction(
        self,
        history: list[CompactionTurn],
        approx_tokens: int,
    ) -> bool: ...

    async def compact(
        self,
        history: list[CompactionTurn],
    ) -> list[CompactionTurn]:
        """Returns a NEW history where old turns have been replaced by one or
        more summary turns. The most recent `keep_recent_turns` are preserved
        verbatim — they're what the model needs for immediate coherence."""
        ...


# ---------------------------------------------------------------------------
# LLMCompactor — default impl
# ---------------------------------------------------------------------------

@dataclass
class LLMCompactor:
    """Default IConversationCompactor — one LLM call replaces a block of old turns.

    Uses ILLMProvider + PromptRegistry from the framework.

        provider = OpenAIProvider(api_key=...)
        registry = make_framework_registry()
        compactor = LLMCompactor(provider=provider, registry=registry)

    Prompt template loaded from `ryuu_cognitive/prompts/compaction/v1.yaml`
    (or any user override the registry resolves to first).
    """

    provider: ILLMProvider
    registry: PromptRegistry
    threshold_tokens: int = 8000
    keep_recent_turns: int = 5
    project: str = "compaction"
    version: str = "v1"
    prompt_name: str = "compact"

    async def needs_compaction(
        self,
        history: list[CompactionTurn],
        approx_tokens: int,
    ) -> bool:
        if approx_tokens > 0:
            return approx_tokens >= self.threshold_tokens
        # Rough fallback: assume ~40 tokens / turn
        return len(history) * 40 >= self.threshold_tokens

    async def compact(
        self,
        history: list[CompactionTurn],
    ) -> list[CompactionTurn]:
        if len(history) <= self.keep_recent_turns:
            return list(history)

        to_compress = history[: -self.keep_recent_turns]
        keep = history[-self.keep_recent_turns:]

        conversation = "\n".join(f"{t.role}: {t.text}" for t in to_compress)
        cfg = self.registry.load(self.project, self.version)
        request = self.registry.build_request(
            cfg, self.prompt_name, include_tools=False, conversation=conversation
        )
        result = await self.provider.complete(request)
        summary_text = (result.content or "").strip()

        summary_turn = CompactionTurn(
            role="summary",
            text=f"[Previous conversation summary]: {summary_text}",
        )
        return [summary_turn, *keep]


# ---------------------------------------------------------------------------
# HierarchicalCompactor — multi-level (advanced)
# ---------------------------------------------------------------------------

@dataclass
class HierarchicalCompactor:
    """Multi-level compactor. When a single summary still pushes the window,
    re-compact the summary itself into a tighter summary. Same pattern as
    Claude Code's recursive summarization.
    """

    provider: ILLMProvider
    registry: PromptRegistry
    threshold_tokens: int = 8000
    keep_recent_turns: int = 5
    max_levels: int = 3
    project: str = "compaction"
    version: str = "v1"
    prompt_name: str = "compact"
    _inner: LLMCompactor = field(init=False)

    def __post_init__(self) -> None:
        self._inner = LLMCompactor(
            provider=self.provider,
            registry=self.registry,
            threshold_tokens=self.threshold_tokens,
            keep_recent_turns=self.keep_recent_turns,
            project=self.project,
            version=self.version,
            prompt_name=self.prompt_name,
        )

    async def needs_compaction(
        self,
        history: list[CompactionTurn],
        approx_tokens: int,
    ) -> bool:
        return await self._inner.needs_compaction(history, approx_tokens)

    async def compact(
        self,
        history: list[CompactionTurn],
    ) -> list[CompactionTurn]:
        current = list(history)
        for _ in range(self.max_levels):
            compacted = await self._inner.compact(current)
            if len(compacted) >= len(current):
                return compacted
            current = compacted
            if len(current) <= self.keep_recent_turns + 2:
                break
        return current
