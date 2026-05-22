from __future__ import annotations

from typing import Protocol, runtime_checkable

from ryuu_eval_core.models import CaseResult, EvalCase, ScoreResult


@runtime_checkable
class EvalTarget(Protocol):
    async def run(self, case: EvalCase) -> CaseResult: ...


@runtime_checkable
class Scorer(Protocol):
    scorer_id: str

    async def score(self, case: EvalCase, output: str) -> ScoreResult: ...
