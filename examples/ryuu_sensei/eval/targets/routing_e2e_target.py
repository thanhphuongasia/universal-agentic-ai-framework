"""RoutingE2ETarget — End-to-end eval cho adaptive routing.

Gọi handler.handle() thật → agent.run() → LLM thật. Tốn tiền.
Output = JSON {"model": actual_model, "text": llm_text} để scorer tách ra.

Hai scorer phối hợp:
  • ModelTierScorer  — kiểm tra model routing đúng tier
  • KeywordScorer    — kiểm tra nội dung output có đủ từ khoá không

Usage:
    target = RoutingE2ETarget.build()
    runner = EvalRunner(
        suite_id="model_routing_e2e",
        target=target,
        scorers=[ModelTierScorer(), KeywordScorer()],
    )
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from ryuu_messaging_core import IncomingMessage, Session
from ryuu_eval_core.models import CaseResult, EvalCase, ScoreResult

from examples.ryuu_sensei.apps.ryuu_handler import RyuuHandler


_EVAL_SCOPE = "eval"


@dataclass
class ModelTierScorer:
    """Pass khi actual model (từ metadata) khớp case.expected['model']."""

    scorer_id: str = "model-tier"

    async def score(self, case: EvalCase, output: str) -> ScoreResult:
        try:
            data = json.loads(output)
            actual = data.get("model", "")
        except (json.JSONDecodeError, AttributeError):
            actual = ""
        expected = case.expected.get("model") if case.expected else None
        passed = actual == expected
        return ScoreResult(
            scorer_id=self.scorer_id,
            passed=passed,
            score=1.0 if passed else 0.0,
            reason=f"routed to {actual!r}, expected {expected!r}",
        )


@dataclass
class KeywordScorer:
    """Pass khi output text chứa tất cả must_mention và không chứa must_not_mention."""

    scorer_id: str = "keyword-coverage"

    async def score(self, case: EvalCase, output: str) -> ScoreResult:
        try:
            text = json.loads(output).get("text", "").lower()
        except (json.JSONDecodeError, AttributeError):
            text = output.lower()

        must = case.expected.get("must_mention", []) if case.expected else []
        must_not = case.expected.get("must_not_mention", []) if case.expected else []

        missing = [kw for kw in must if kw.lower() not in text]
        found_bad = [kw for kw in must_not if kw.lower() in text]

        passed = not missing and not found_bad
        parts = []
        if missing:
            parts.append(f"missing: {missing}")
        if found_bad:
            parts.append(f"unexpected: {found_bad}")
        reason = "; ".join(parts) if parts else "all keywords OK"

        return ScoreResult(
            scorer_id=self.scorer_id,
            passed=passed,
            score=1.0 if passed else 0.0,
            reason=reason,
        )


@dataclass
class RoutingE2ETarget:
    """Eval target that calls handler.handle() → real LLM call."""

    _handler: RyuuHandler

    @classmethod
    def build(
        cls,
        adaptive_routing: bool = True,
        base_model: str = "gpt-4o-mini",
    ) -> "RoutingE2ETarget":
        handler = RyuuHandler(memory_backbone=None)
        s = handler.get_settings(_EVAL_SCOPE)
        s.model = base_model
        s.adaptive_routing = adaptive_routing
        return cls(_handler=handler)

    async def run(self, case: EvalCase) -> CaseResult:
        text = (
            case.input.get("message", "")
            if isinstance(case.input, dict)
            else str(case.input)
        )

        msg = IncomingMessage(
            channel="eval",
            sender_id=_EVAL_SCOPE,
            conversation_id=case.case_id,
            text=text,
        )
        session = Session(
            scope_key=_EVAL_SCOPE,
            channel="eval",
            sender_id=_EVAL_SCOPE,
            conversation_id=case.case_id,
        )

        try:
            outgoing = await self._handler.handle(msg, session)
            actual_model = outgoing.metadata.get("model", "unknown")
            output = json.dumps({"model": actual_model, "text": outgoing.text}, ensure_ascii=False)
            return CaseResult(case=case, output=output)
        except Exception as exc:  # noqa: BLE001
            return CaseResult(case=case, output="", error=str(exc))
