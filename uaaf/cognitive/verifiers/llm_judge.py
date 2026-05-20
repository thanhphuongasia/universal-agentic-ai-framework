"""LLMJudgeVerifier — uses an LLM to score and judge output quality."""

from __future__ import annotations

import re
from typing import Any

from uaaf.cognitive.verifier import VerificationResult
from uaaf.providers.llm import CompletionRequest, ILLMProvider, Message
from uaaf_workflow.context import ExecutionContext

_DEFAULT_MODEL = "gpt-4o-mini"

_JUDGE_PROMPT = """\
You are an output quality judge. Evaluate the following output and respond ONLY in this exact format:
SCORE:<float 0.0-1.0>
VERDICT:PASS or VERDICT:FAIL
REASON:<one line reason>

Output to evaluate:
{output}
"""

_SCORE_RE = re.compile(r"SCORE:\s*([\d.]+)")
_VERDICT_RE = re.compile(r"VERDICT:\s*(PASS|FAIL)")
_REASON_RE = re.compile(r"REASON:\s*(.+)")


class LLMJudgeVerifier:
    """Asks an LLM to rate output quality and returns pass/fail based on a threshold."""

    verifier_id = "llm_judge"

    def __init__(
        self,
        provider: ILLMProvider,
        model: str | None = None,
        threshold: float = 0.7,
    ) -> None:
        self._provider = provider
        self._model = model
        self._threshold = threshold

    async def verify(
        self,
        output: str,
        context: ExecutionContext,
        metadata: dict[str, Any] | None = None,
    ) -> VerificationResult:
        prompt = _JUDGE_PROMPT.format(output=output)
        request = CompletionRequest(
            messages=[Message(role="user", content=prompt)],
            model=self._model or _DEFAULT_MODEL,
        )
        response = await self._provider.complete(request)
        return self._parse(response.content)

    def _parse(self, text: str) -> VerificationResult:
        score_m = _SCORE_RE.search(text)
        verdict_m = _VERDICT_RE.search(text)
        reason_m = _REASON_RE.search(text)

        if score_m is None or verdict_m is None:
            return VerificationResult(
                passed=False, confidence=0.0, feedback="Judge response unparseable"
            )

        score = float(score_m.group(1))
        passed = score >= self._threshold
        reason = reason_m.group(1).strip() if reason_m else ""
        return VerificationResult(passed=passed, confidence=score, feedback=reason)
