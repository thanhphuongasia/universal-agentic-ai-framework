"""Prompt metering — estimate token usage per component.

Generic utility for handlers that assemble prompts from named blocks (system,
memory, history, profile, …). Lets the handler track WHERE tokens go without
calling the LLM tokenizer — useful for cost tracing, `/last`-style commands,
and triggering compaction.

Estimation strategy:
  chars / 4 — standard rule-of-thumb for OpenAI BPE tokenizers on English-ish
  text. Vietnamese and other non-Latin scripts run ~1.5x higher, so this
  under-estimates for them, but it's good enough for *relative* sizing across
  components. For exact counts, integrate `tiktoken` or use the provider's
  measured `input_tokens` after the call.

Why not tiktoken: it's a 5MB dependency with C extensions. This module stays
pure-Python so `ryuu-cognitive` can be installed anywhere without surprises.
Add tiktoken at the application layer if you need accuracy.

Example:
    from ryuu_cognitive.context import build_prompt_breakdown

    breakdown = build_prompt_breakdown({
        "system":   self._build_instructions(),
        "memory":   recall_context,
        "history":  history_block,
        "user_msg": msg.text,
    })
    # → {"system": 550, "memory": 47, "history": 100, "user_msg": 10, "total_est": 707}

    stats.last_breakdown = breakdown
"""

from __future__ import annotations


def est_tokens(text: str) -> int:
    """Estimate token count from character length.

    Returns 0 for empty/None, else max(1, len(text) // 4).
    """
    if not text:
        return 0
    return max(1, len(text) // 4)


def build_prompt_breakdown(blocks: dict[str, str]) -> dict[str, int]:
    """Compute per-block token estimates plus a `total_est` sum.

    `blocks` maps a label (e.g. "system", "memory") to the raw text that
    will be sent to the LLM under that label. Returns a new dict with the
    same keys mapped to int estimates, plus a `total_est` aggregate.

    Order of keys is preserved (Python 3.7+ dict semantics) so callers can
    rely on iteration order for display.
    """
    out: dict[str, int] = {label: est_tokens(text) for label, text in blocks.items()}
    out["total_est"] = sum(out.values())
    return out


__all__ = ["est_tokens", "build_prompt_breakdown"]
