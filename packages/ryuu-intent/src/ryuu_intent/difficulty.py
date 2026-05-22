"""Cheap difficulty classifier for Phase 14.3 AdaptiveStrategy.

Single-purpose: classify a user query into "trivial" | "medium" | "hard".
Used by AdaptiveStrategy to pick the right model tier + iteration budget
without spending a full reasoning call upfront.

The prompt template lives in `ryuu_intent/prompts/difficulty/v1.yaml` so
users can override without redeploying code. Use:

    from ryuu_prompts import PromptRegistry, package_default_root
    registry = PromptRegistry(prompts_root=package_default_root("ryuu_intent"))
    cfg = registry.load("difficulty", "v1")
"""

from __future__ import annotations

from typing import Literal

# Kept in sync with prompts/difficulty/v1.yaml for callers who don't want to
# wire a PromptRegistry. New code should load the YAML via registry instead.
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
