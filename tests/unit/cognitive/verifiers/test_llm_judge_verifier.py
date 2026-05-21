"""Unit tests for LLMJudgeVerifier — P2-T03."""

from __future__ import annotations

import pytest

from ryuu._testing.fakes import FakeLLMProvider
from ryuu.cognitive.verifiers.llm_judge import LLMJudgeVerifier
from ryuu.providers.llm import Response, TokenUsage
from ryuu_workflow.context import ContextScope, ExecutionContext


def _resp(text: str) -> Response:
    return Response(content=text, model="fake", usage=TokenUsage(10, 5), finish_reason="stop")


@pytest.fixture()
def ctx() -> ExecutionContext:
    return ExecutionContext(
        scope=ContextScope(user_id="u1", session_id="s1", domain="test"),
        correlation_id="c1",
    )


class TestLLMJudgeVerifier:
    @pytest.mark.asyncio
    async def test_pass_above_threshold(self, ctx):
        provider = FakeLLMProvider(responses=[_resp("SCORE:0.90\nVERDICT:PASS\nREASON:Looks good")])
        v = LLMJudgeVerifier(provider=provider, threshold=0.7)
        result = await v.verify("some output", ctx)
        assert result.passed is True
        assert result.confidence == pytest.approx(0.90)

    @pytest.mark.asyncio
    async def test_fail_below_threshold(self, ctx):
        provider = FakeLLMProvider(responses=[_resp("SCORE:0.50\nVERDICT:FAIL\nREASON:Too short")])
        v = LLMJudgeVerifier(provider=provider, threshold=0.7)
        result = await v.verify("some output", ctx)
        assert result.passed is False
        assert result.confidence == pytest.approx(0.50)
        assert "Too short" in result.feedback

    @pytest.mark.asyncio
    async def test_pass_exactly_at_threshold(self, ctx):
        provider = FakeLLMProvider(responses=[_resp("SCORE:0.70\nVERDICT:PASS\nREASON:OK")])
        v = LLMJudgeVerifier(provider=provider, threshold=0.7)
        result = await v.verify("output", ctx)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_unparseable_response(self, ctx):
        provider = FakeLLMProvider(responses=[_resp("garbage response no score")])
        v = LLMJudgeVerifier(provider=provider)
        result = await v.verify("output", ctx)
        assert result.passed is False
        assert result.confidence == 0.0
        assert "unparseable" in result.feedback.lower()

    @pytest.mark.asyncio
    async def test_verifier_id(self, ctx):
        v = LLMJudgeVerifier(provider=FakeLLMProvider(responses=[]))
        assert v.verifier_id == "llm_judge"
