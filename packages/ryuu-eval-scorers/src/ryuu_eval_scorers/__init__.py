"""ryuu-eval-scorers — Built-in scorer implementations.

All scorers satisfy the `Scorer` Protocol from ryuu-eval-core:
    ExactMatch   — strict string equality
    Constraint   — predicate-based constraint check
    Threshold    — numeric threshold check
    Composite    — combine multiple scorers
    LLMJudge     — LLM-as-judge
"""

from ryuu_eval_scorers.scorers import (
    Composite,
    Constraint,
    ExactMatch,
    LLMJudge,
    Threshold,
)

__version__ = "0.3.0a1"

__all__ = ["Composite", "Constraint", "ExactMatch", "LLMJudge", "Threshold"]
