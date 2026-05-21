from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    input: str
    expected: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)


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
