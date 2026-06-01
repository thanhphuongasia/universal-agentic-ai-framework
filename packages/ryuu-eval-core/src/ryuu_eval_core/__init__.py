"""ryuu-eval-core — Eval framework primitives (no scorer impls).

Public API:
    EvalCase, CaseResult, SuiteResult, ScoreResult — value types
    EvalTarget, Scorer                              — Protocols
    EvalRunner                                      — orchestrator
    FixtureLoader                                   — YAML loader
    TerminalRenderer, GitHubActionsRenderer         — output formatters

Oracle ground truth (OracleFixture, OracleWorkflow, IOracleStrategy, …)
has moved to the `ryuu-eval-oracle` package.

For built-in scorer implementations (ExactMatch, Constraint, Threshold, …)
install the sibling `ryuu-eval-scorers` package.
"""

from ryuu_eval_core.fixture_loader import FixtureLoader
from ryuu_eval_core.models import (
    CaseResult,
    EvalCase,
    EvalCaseTemplate,
    ExternalProject,
    ProgressEvent,
    ProgressEventType,
    ScoreResult,
    SuiteResult,
)
from ryuu_eval_core.protocols import (
    EvalTarget,
    IEvalRunStore,
    ITestCaseStore,
    Scorer,
)
from ryuu_eval_core.runner import EvalRunner

__version__ = "0.4.0a1"

__all__ = [
    "CaseResult",
    "EvalCase",
    "EvalCaseTemplate",
    "EvalRunner",
    "EvalTarget",
    "ExternalProject",
    "FixtureLoader",
    "IEvalRunStore",
    "ITestCaseStore",
    "ProgressEvent",
    "ProgressEventType",
    "Scorer",
    "ScoreResult",
    "SuiteResult",
]
