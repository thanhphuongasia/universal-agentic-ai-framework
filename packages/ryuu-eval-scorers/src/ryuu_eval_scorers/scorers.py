from __future__ import annotations

import json
from typing import Any, Callable

from ryuu_eval_core.models import EvalCase, ScoreResult


class ExactMatch:
    scorer_id = "exact-match"

    async def score(self, case: EvalCase, output: str) -> ScoreResult:
        passed = str(case.expected).strip() == output.strip()
        return ScoreResult(scorer_id=self.scorer_id, score=1.0 if passed else 0.0, passed=passed)


class Constraint:
    def __init__(self, scorer_id: str, constraint_fn: Callable[[str, EvalCase], bool]) -> None:
        self.scorer_id = scorer_id
        self._fn = constraint_fn

    async def score(self, case: EvalCase, output: str) -> ScoreResult:
        passed = bool(self._fn(output, case))
        return ScoreResult(scorer_id=self.scorer_id, score=1.0 if passed else 0.0, passed=passed)


class Threshold:
    def __init__(self, scorer_id: str, min_score: float, score_fn: Callable[[str, EvalCase], float]) -> None:
        self.scorer_id = scorer_id
        self._min = min_score
        self._fn = score_fn

    async def score(self, case: EvalCase, output: str) -> ScoreResult:
        s = float(self._fn(output, case))
        return ScoreResult(scorer_id=self.scorer_id, score=s, passed=s >= self._min)


class Composite:
    def __init__(self, scorer_id: str, scorers: list[Any], require_all: bool = True) -> None:
        self.scorer_id = scorer_id
        self._scorers = scorers
        self._require_all = require_all

    async def score(self, case: EvalCase, output: str) -> ScoreResult:
        results = [await s.score(case, output) for s in self._scorers]
        avg = sum(r.score for r in results) / len(results) if results else 0.0
        passed = (all(r.passed for r in results) if self._require_all
                  else any(r.passed for r in results))
        return ScoreResult(scorer_id=self.scorer_id, score=avg, passed=passed)


class LLMJudge:
    def __init__(
        self,
        scorer_id: str,
        provider: Any,
        prompt_template: str,
        threshold: float = 0.7,
    ) -> None:
        self.scorer_id = scorer_id
        self._provider = provider
        self._template = prompt_template
        self._threshold = threshold

    async def score(self, case: EvalCase, output: str) -> ScoreResult:
        from ryuu_providers.llm import CompletionRequest, Message

        prompt = self._template.format(
            input=case.input, output=output, expected=case.expected
        )
        req = CompletionRequest(
            messages=[Message(role="user", content=prompt)], max_tokens=256
        )
        resp = await self._provider.complete(req)
        text = resp.content.strip()
        try:
            data = json.loads(text)
            score = float(data.get("score", 0.0))
        except (json.JSONDecodeError, ValueError):
            score = 1.0 if "pass" in text.lower() else 0.0
        return ScoreResult(
            scorer_id=self.scorer_id,
            score=score,
            passed=score >= self._threshold,
            reason=text,
        )
