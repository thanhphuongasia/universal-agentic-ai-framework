from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    input: Any  # str for simple LLM eval, dict for structured/complex inputs
    expected: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvalCaseTemplate:
    """Schema for a category of eval case — UI form generator.

    Multiple templates can target the same suite_id (Q1=B): e.g. CRUD suite
    có "happy_path", "edge_case", "regression" templates. Each defines an
    input/expected JSON Schema so UI auto-generates the form (Q2=A via
    @rjsf/core or equivalent).

    Templates persist as YAML files in the suite directory by convention;
    project's runner_factory loads them via FixtureLoader.list_templates().
    """

    template_id: str
    """Unique identifier across all templates (UUID or kebab-case slug)."""

    suite_id: str
    """Which suite this template belongs to. Multiple templates per suite OK."""

    title: str
    """Display name shown in UI gallery."""

    description: str = ""
    """Multi-line description shown when user hovers/expands template."""

    input_schema: dict[str, Any] = field(default_factory=dict)
    """JSON Schema (draft-07) for the case input. Drives form generation."""

    expected_schema: dict[str, Any] = field(default_factory=dict)
    """JSON Schema for the expected output. Used for form gen + diff view."""

    examples: list[dict[str, Any]] = field(default_factory=list)
    """Pre-filled example cases. Each entry: {input: {...}, expected: {...}}.
    User clones one to seed a new case."""

    tags: list[str] = field(default_factory=list)
    """Categorization for UI filtering: ["smoke", "edge_case", "security"]."""


# ----------------------------------------------------------------------------
# ProgressEvent — standard SSE event for streaming runs
# ----------------------------------------------------------------------------

ProgressEventType = Literal[
    "suite_start",     # payload: {total_cases, suite_id}
    "case_start",      # payload: {case_id, index, total}
    "llm_attempt",     # payload: {case_id, attempt, model}
    "llm_done",        # payload: {case_id, latency_ms, cost_usd}
    "refine_attempt",  # payload: {case_id, iteration, feedback}
    "refine_done",     # payload: {case_id, refine_count, passed}
    "case_done",       # payload: {case_id, passed, scores, latency_ms}
    "suite_done",      # payload: {pass_rate, total_cost_usd}
    "error",           # payload: {case_id?, error_type, message}
]


@dataclass(frozen=True)
class ProgressEvent:
    """Standardized event emitted during streaming eval runs.

    Consumers (UI via SSE, test reporters, dashboards) all parse same shape.
    """

    type: ProgressEventType
    payload: dict[str, Any] = field(default_factory=dict)
    case_id: str | None = None
    ts: float = 0.0

    def __post_init__(self) -> None:
        if self.ts == 0.0:
            object.__setattr__(self, "ts", time.time())


@dataclass(frozen=True)
class ScoreResult:
    scorer_id: str
    score: float
    passed: bool
    reason: str = ""


@dataclass
class CaseResult:
    case: EvalCase
    output: str
    scores: list[ScoreResult] = field(default_factory=list)
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    error: str | None = None
    refine_count: int = 0
    """How many refine iterations Evaluator needed (if target wraps Evaluator)."""
    refine_feedback_history: list[str] = field(default_factory=list)
    """Per-iteration verifier feedback during refine loop."""

    @property
    def passed(self) -> bool:
        return self.error is None and all(s.passed for s in self.scores)


@dataclass
class SuiteResult:
    suite_id: str
    cases: list[CaseResult] = field(default_factory=list)
    total_cost_usd: float = 0.0

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.cases if c.passed)

    @property
    def total_count(self) -> int:
        return len(self.cases)

    @property
    def pass_rate(self) -> float:
        if not self.cases:
            return 0.0
        return self.passed_count / self.total_count
