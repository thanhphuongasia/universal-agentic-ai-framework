"""ryuu-eval — back-compat metapackage.

After Phase 8.15:
  • ryuu-eval-core      Types, Protocols, runner, renderers, fixture loader
  • ryuu-eval-scorers   Built-in scorers (ExactMatch, Constraint, Threshold, Composite, LLMJudge)

Old imports continue to work via re-exports.
"""

from ryuu_eval_core import (
    CaseResult,
    EvalCase,
    EvalRunner,
    EvalTarget,
    FixtureLoader,
    ScoreResult,
    Scorer,
    SuiteResult,
)
from ryuu_eval_scorers import Composite, Constraint, ExactMatch, LLMJudge, Threshold

__all__ = [
    "CaseResult", "EvalCase", "EvalRunner", "EvalTarget", "FixtureLoader",
    "Scorer", "ScoreResult", "SuiteResult",
    "Composite", "Constraint", "ExactMatch", "LLMJudge", "Threshold",
]
