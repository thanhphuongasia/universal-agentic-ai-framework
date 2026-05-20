"""Unit tests for GroundTruthVerifier — P2-T04."""

from __future__ import annotations

import pytest

from uaaf.cognitive.verifiers.ground_truth import GroundTruthVerifier
from uaaf_workflow.context import ContextScope, ExecutionContext


@pytest.fixture()
def ctx() -> ExecutionContext:
    return ExecutionContext(
        scope=ContextScope(user_id="u1", session_id="s1", domain="test"),
        correlation_id="c1",
    )


class TestExactMode:
    @pytest.mark.asyncio
    async def test_pass_exact_match(self, ctx):
        v = GroundTruthVerifier(reference="hello world", mode="exact")
        result = await v.verify("hello world", ctx)
        assert result.passed is True
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_pass_strips_whitespace(self, ctx):
        v = GroundTruthVerifier(reference="hello world", mode="exact")
        result = await v.verify("  hello world  ", ctx)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_fail_different(self, ctx):
        v = GroundTruthVerifier(reference="hello world", mode="exact")
        result = await v.verify("hello", ctx)
        assert result.passed is False
        assert result.confidence == 0.0


class TestSubstringMode:
    @pytest.mark.asyncio
    async def test_pass_reference_in_output(self, ctx):
        v = GroundTruthVerifier(reference="key phrase", mode="substring")
        result = await v.verify("this contains key phrase here", ctx)
        assert result.passed is True
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_fail_not_in_output(self, ctx):
        v = GroundTruthVerifier(reference="missing", mode="substring")
        result = await v.verify("nothing here", ctx)
        assert result.passed is False
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_default_mode_is_substring(self, ctx):
        v = GroundTruthVerifier(reference="word")
        result = await v.verify("a word appears", ctx)
        assert result.passed is True


class TestWordOverlapMode:
    @pytest.mark.asyncio
    async def test_pass_high_overlap(self, ctx):
        v = GroundTruthVerifier(reference="the cat sat on mat", mode="word_overlap", threshold=0.5)
        result = await v.verify("the cat sat on the mat", ctx)
        assert result.passed is True
        assert result.confidence > 0.5

    @pytest.mark.asyncio
    async def test_fail_low_overlap(self, ctx):
        v = GroundTruthVerifier(reference="apple banana cherry", mode="word_overlap", threshold=0.5)
        result = await v.verify("dog fish bird", ctx)
        assert result.passed is False
        assert result.confidence == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_identical_sentences_confidence_1(self, ctx):
        v = GroundTruthVerifier(reference="hello world", mode="word_overlap")
        result = await v.verify("hello world", ctx)
        assert result.confidence == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_verifier_id(self, ctx):
        v = GroundTruthVerifier(reference="x")
        assert v.verifier_id == "ground_truth"
