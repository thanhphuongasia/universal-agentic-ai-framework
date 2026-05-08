"""Unit tests for VerifierPipeline — P2-T05."""

from __future__ import annotations

import pytest

from uaaf._testing.fakes import FakeVerifier
from uaaf.cognitive.verifiers.pipeline import PipelineMode, VerifierPipeline
from uaaf.runtime.context import ContextScope, ExecutionContext


@pytest.fixture()
def ctx() -> ExecutionContext:
    return ExecutionContext(
        scope=ContextScope(user_id="u1", session_id="s1", domain="test"),
        correlation_id="c1",
    )


def _verifiers(pass_seq: list[bool], confidence_seq: list[float] | None = None):
    confs = confidence_seq or [1.0 if p else 0.0 for p in pass_seq]
    return [FakeVerifier(pass_sequence=[p], confidence_sequence=[c]) for p, c in zip(pass_seq, confs, strict=False)]


class TestAllPass:
    @pytest.mark.asyncio
    async def test_all_pass(self, ctx):
        pipeline = VerifierPipeline(verifiers=_verifiers([True, True, True]))
        result = await pipeline.verify("output", ctx)
        assert result.passed is True
        assert result.confidence == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_one_fail(self, ctx):
        pipeline = VerifierPipeline(verifiers=_verifiers([True, False, True]))
        result = await pipeline.verify("output", ctx)
        assert result.passed is False
        assert result.confidence == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_confidence_is_min(self, ctx):
        pipeline = VerifierPipeline(
            verifiers=_verifiers([True, True], confidence_seq=[0.9, 0.6])
        )
        result = await pipeline.verify("output", ctx)
        assert result.confidence == pytest.approx(0.6)


class TestAnyPass:
    @pytest.mark.asyncio
    async def test_any_pass(self, ctx):
        pipeline = VerifierPipeline(
            verifiers=_verifiers([False, True, False]), mode=PipelineMode.ANY_PASS
        )
        result = await pipeline.verify("output", ctx)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_none_pass(self, ctx):
        pipeline = VerifierPipeline(
            verifiers=_verifiers([False, False]), mode=PipelineMode.ANY_PASS
        )
        result = await pipeline.verify("output", ctx)
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_confidence_is_max(self, ctx):
        pipeline = VerifierPipeline(
            verifiers=_verifiers([True, True], confidence_seq=[0.4, 0.8]),
            mode=PipelineMode.ANY_PASS,
        )
        result = await pipeline.verify("output", ctx)
        assert result.confidence == pytest.approx(0.8)


class TestThreshold:
    @pytest.mark.asyncio
    async def test_threshold_met(self, ctx):
        pipeline = VerifierPipeline(
            verifiers=_verifiers([True, False, True]),
            mode=PipelineMode.THRESHOLD,
            threshold_count=2,
        )
        result = await pipeline.verify("output", ctx)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_threshold_not_met(self, ctx):
        pipeline = VerifierPipeline(
            verifiers=_verifiers([True, False, False]),
            mode=PipelineMode.THRESHOLD,
            threshold_count=2,
        )
        result = await pipeline.verify("output", ctx)
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_confidence_is_mean(self, ctx):
        pipeline = VerifierPipeline(
            verifiers=_verifiers([True, True], confidence_seq=[0.6, 0.8]),
            mode=PipelineMode.THRESHOLD,
            threshold_count=1,
        )
        result = await pipeline.verify("output", ctx)
        assert result.confidence == pytest.approx(0.7)


class TestMisc:
    @pytest.mark.asyncio
    async def test_verifier_id(self, ctx):
        p = VerifierPipeline(verifiers=[])
        assert p.verifier_id == "pipeline"

    @pytest.mark.asyncio
    async def test_feedback_joins_failed(self, ctx):
        v1 = FakeVerifier(pass_sequence=[False], confidence_sequence=[0.0], feedback="bad schema")
        v2 = FakeVerifier(pass_sequence=[False], confidence_sequence=[0.0], feedback="bad content")
        pipeline = VerifierPipeline(verifiers=[v1, v2])
        result = await pipeline.verify("output", ctx)
        assert "bad schema" in result.feedback
        assert "bad content" in result.feedback


# ---------------------------------------------------------------------------
# Empty pipeline — returns True immediately (coverage line 40)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verify_with_empty_verifiers_returns_passed(ctx) -> None:
    pipeline = VerifierPipeline(verifiers=[])
    result = await pipeline.verify("any output", ctx)
    assert result.passed is True
    assert result.confidence == 1.0
