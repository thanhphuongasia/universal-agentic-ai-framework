"""ryuu-intent — Intent classification primitives.

Public API:
    Difficulty classification:
        Difficulty           Literal["trivial", "medium", "hard"]
        normalize_difficulty Map raw LLM output → canonical Difficulty
        DEFAULT_PROMPT       Back-compat constant (canonical: difficulty/v1.yaml)

    Intent analysis:
        LLMIntentAnalyzer    LLM-backed IIntentAnalyzer impl
        INTENT_SYSTEM_PROMPT Back-compat constant (canonical: intent/v1.yaml)

Ships prompt YAMLs at `prompts/{difficulty,intent}/v1.yaml`. Use with PromptRegistry:

    from ryuu_prompts import make_framework_registry
    registry = make_framework_registry()
    cfg = registry.load("difficulty", "v1")
"""

from ryuu_intent.difficulty import (
    DEFAULT_PROMPT,
    Difficulty,
    normalize_difficulty,
)
from ryuu_intent.llm_analyzer import INTENT_SYSTEM_PROMPT, LLMIntentAnalyzer

__version__ = "0.3.0a1"

__all__ = [
    "DEFAULT_PROMPT",
    "Difficulty",
    "INTENT_SYSTEM_PROMPT",
    "LLMIntentAnalyzer",
    "normalize_difficulty",
]
