"""RoutingTarget — EvalTarget cho adaptive routing.

Test difficulty_fn + tier_models mapping. `difficulty_fn` phải được truyền vào
từ caller — thường là LLMIntentAnalyzer hoặc callable tự định nghĩa.

Usage:
    target = RoutingTarget.build()
    scorer = ModelTierScorer()
    runner = EvalRunner(suite_id="adaptive_routing", target=target, scorers=[scorer])
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ryuu_cognitive.strategies.adaptive_strategy import _DEFAULT_TIER_MODELS
from ryuu_eval_core.models import CaseResult, EvalCase, ScoreResult


@dataclass
class ModelTierScorer:
    """Pass khi actual model khớp case.expected['model']."""

    scorer_id: str = "model-tier"

    async def score(self, case: EvalCase, output: str) -> ScoreResult:
        expected = case.expected.get("model") if case.expected else None
        passed = output == expected
        return ScoreResult(
            scorer_id=self.scorer_id,
            passed=passed,
            score=1.0 if passed else 0.0,
            reason=f"routed to {output!r}, expected {expected!r}",
        )


@dataclass
class RoutingTarget:
    """Eval target: classify query → pick model. No LLM call."""

    _difficulty_fn: Callable[[str], str]
    _tier_models: dict[str, str]
    _allowed_models: tuple[str, ...]
    _fallback_model: str

    @classmethod
    def build(
        cls,
        difficulty_fn: Callable[[str], str],
        tier_models: dict[str, str] | None = None,
        allowed_models: tuple[str, ...] = ("gpt-4o-mini", "gpt-4o"),
        fallback_model: str = "gpt-4o-mini",
    ) -> "RoutingTarget":
        return cls(
            _difficulty_fn=difficulty_fn,
            _tier_models=tier_models or dict(_DEFAULT_TIER_MODELS),
            _allowed_models=allowed_models,
            _fallback_model=fallback_model,
        )

    async def run(self, case: EvalCase) -> CaseResult:
        text = (
            case.input.get("message", "")
            if isinstance(case.input, dict)
            else str(case.input)
        )
        difficulty = self._difficulty_fn(text)
        candidate = self._tier_models.get(difficulty, self._fallback_model)
        model = candidate if candidate in self._allowed_models else self._fallback_model
        return CaseResult(case=case, output=model)
