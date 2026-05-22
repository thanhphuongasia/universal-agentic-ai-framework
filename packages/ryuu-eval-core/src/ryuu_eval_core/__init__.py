"""ryuu-eval-core — Eval framework primitives (no scorer impls).

Public API:
    EvalCase, CaseResult, SuiteResult, ScoreResult — value types
    EvalTarget, Scorer                              — Protocols
    EvalRunner                                      — orchestrator
    FixtureLoader                                   — YAML loader
    TerminalRenderer, GitHubActionsRenderer         — output formatters

For built-in scorer implementations (ExactMatch, Constraint, Threshold, …)
install the sibling `ryuu-eval-scorers` package.
"""

from ryuu_eval_core.fixture_loader import FixtureLoader
from ryuu_eval_core.models import (
    CaseResult,
    EvalCase,
    EvalCaseTemplate,
    ProgressEvent,
    ProgressEventType,
    ScoreResult,
    SuiteResult,
)
from ryuu_eval_core.protocols import EvalTarget, Scorer
from ryuu_eval_core.runner import EvalRunner

__version__ = "0.4.0a1"

__all__ = [
    "CaseResult",
    "EvalCase",
    "EvalCaseTemplate",
    "EvalRunner",
    "EvalTarget",
    "FixtureLoader",
    "ProgressEvent",
    "ProgressEventType",
    "Scorer",
    "ScoreResult",
    "SuiteResult",
]
