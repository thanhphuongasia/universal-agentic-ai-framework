"""Backward-compat shim. Canonical source: `ryuu_intent.difficulty`.

Old imports continue to work:
    from ryuu._difficulty_classifier import normalize_difficulty, Difficulty, DEFAULT_PROMPT

New code should use:
    from ryuu_intent import normalize_difficulty, Difficulty
"""

from ryuu_intent.difficulty import (
    DEFAULT_PROMPT,
    Difficulty,
    normalize_difficulty,
)

__all__ = ["DEFAULT_PROMPT", "Difficulty", "normalize_difficulty"]
