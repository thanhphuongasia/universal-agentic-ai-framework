"""Contract tests — every IVerifier must satisfy the protocol shape."""

from __future__ import annotations

import pytest

from uaaf._testing.fakes import FakeLLMProvider
from uaaf.cognitive.verifier import IVerifier, VerificationResult
from uaaf.cognitive.verifiers.ground_truth import GroundTruthVerifier
from uaaf.cognitive.verifiers.llm_judge import LLMJudgeVerifier
from uaaf.cognitive.verifiers.pipeline import VerifierPipeline
from uaaf.cognitive.verifiers.schema import SchemaVerifier
from uaaf.providers.llm import Response, TokenUsage
from uaaf_workflow.context import ContextScope, ExecutionContext


@pytest.fixture()
def ctx() -> ExecutionContext:
    return ExecutionContext(
        scope=ContextScope(user_id="u1", session_id="s1", domain="test"),
        correlation_id="c1",
    )


def _fake_provider(text: str) -> FakeLLMProvider:
    return FakeLLMProvider(
        responses=[Response(content=text, model="fake", usage=TokenUsage(10, 5), finish_reason="stop")]
    )


@pytest.fixture(
    params=[
        pytest.param("schema", id="schema"),
        pytest.param("llm_judge", id="llm_judge"),
        pytest.param("ground_truth", id="ground_truth"),
        pytest.param("pipeline", id="pipeline"),
    ]
)
def verifier(request: pytest.FixtureRequest) -> IVerifier:
    name = request.param
    if name == "schema":
        return SchemaVerifier(required_keys=["key"])
    if name == "llm_judge":
        return LLMJudgeVerifier(
            provider=_fake_provider("SCORE:0.80\nVERDICT:PASS\nREASON:Good"),
            threshold=0.7,
        )
    if name == "ground_truth":
        return GroundTruthVerifier(reference="expected")
    # pipeline wrapping schema
    return VerifierPipeline(verifiers=[SchemaVerifier(required_keys=[])])


class TestVerifierContract:
    def test_has_verifier_id(self, verifier: IVerifier):
        assert isinstance(verifier.verifier_id, str)
        assert verifier.verifier_id != ""

    def test_is_iverifier(self, verifier: IVerifier):
        assert isinstance(verifier, IVerifier)

    @pytest.mark.asyncio
    async def test_verify_returns_verification_result(self, verifier: IVerifier, ctx: ExecutionContext):
        import json

        output = json.dumps({"key": "value"})
        result = await verifier.verify(output, ctx)
        assert isinstance(result, VerificationResult)
        assert isinstance(result.passed, bool)
        assert 0.0 <= result.confidence <= 1.0
        assert isinstance(result.feedback, str)

    @pytest.mark.asyncio
    async def test_verify_accepts_metadata(self, verifier: IVerifier, ctx: ExecutionContext):
        import json

        output = json.dumps({"key": "value"})
        result = await verifier.verify(output, ctx, metadata={"hint": "test"})
        assert isinstance(result, VerificationResult)
