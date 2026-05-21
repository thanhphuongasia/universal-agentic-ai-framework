"""Cheap difficulty classifier helper for Phase 14.3 AdaptiveStrategy.

Single-purpose: classify a user query into "trivial" | "medium" | "hard".
Default uses gpt-4o-mini with max_tokens=5 (cost: ~$0.00005 per call).
"""

from __future__ import annotations

from typing import Literal

DEFAULT_PROMPT = (
    "Classify query difficulty. Output ONLY one word: trivial|medium|hard.\n"
    "  trivial = single-fact lookup, simple greeting\n"
    "  medium  = 2-3 step reasoning, definition + example\n"
    "  hard    = multi-step analysis, planning, complex synthesis"
)

Difficulty = Literal["trivial", "medium", "hard"]


def normalize_difficulty(raw: str) -> Difficulty:
    """Map raw classifier output to canonical difficulty token.

    Fallback to 'medium' for unrecognized output.
    """
    cleaned = raw.strip().lower().split()[0] if raw.strip() else "medium"
    cleaned = cleaned.rstrip(".,:;!?")
    if cleaned in ("trivial", "easy", "simple"):
        return "trivial"
    if cleaned in ("hard", "complex", "difficult", "extreme"):
        return "hard"
    return "medium"
