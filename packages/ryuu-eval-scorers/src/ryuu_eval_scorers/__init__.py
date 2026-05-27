"""ryuu-eval-scorers — Built-in scorer implementations.

All scorers satisfy the `Scorer` Protocol from ryuu-eval-core:
    ExactMatch        — strict string equality
    Contains          — substring presence check
    Regex             — regex pattern match
    Constraint        — predicate-based constraint check
    Threshold         — numeric threshold check
    Composite         — combine multiple scorers
    LLMJudge          — LLM-as-judge with built-in criteria templates
    SemanticSimilarity — convenience LLMJudge for semantic_match
    StructuredScorer  — precision/recall/F1 on nested JSON dicts
"""

from ryuu_eval_scorers.scorers import (
    Composite,
    Constraint,
    Contains,
    ExactMatch,
    LLMJudge,
    Regex,
    SemanticSimilarity,
    StructuredScorer,
    Threshold,
)

__version__ = "0.3.0a1"

__all__ = [
    "Composite",
    "Constraint",
    "Contains",
    "ExactMatch",
    "LLMJudge",
    "Regex",
    "SemanticSimilarity",
    "StructuredScorer",
    "Threshold",
]
