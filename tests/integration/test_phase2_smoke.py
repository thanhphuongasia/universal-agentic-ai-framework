"""Phase 2 integration smoke — EvaluatorOptimizerStrategy + real VerifierPipeline."""

from __future__ import annotations

import json

import pytest

from ryuu._testing.fakes import FakeAgentPool
from ryuu.cognitive.strategies.evaluator_optimizer import EvaluatorOptimizerStrategy
from ryuu.cognitive.verifiers.ground_truth import GroundTruthVerifier
from ryuu.cognitive.verifiers.pipeline import PipelineMode, VerifierPipeline
from ryuu.cognitive.verifiers.schema import SchemaVerifier
from ryuu.execution.agent import AgentResult
from ryuu.intent.models import ComplexityLevel, StructuredIntent
from ryuu_workflow.context import ContextScope, ExecutionContext


@pytest.fixture()
def ctx() -> ExecutionContext:
    return ExecutionContext(
        scope=ContextScope(user_id="u1", session_id="s1", domain="test"),
        correlation_id="c1",
    )


@pytest.fixture()
def high_intent() -> StructuredIntent:
    return StructuredIntent(
        intent_type="generate",
        action="create_summary",
        entities={},
        complexity=ComplexityLevel.HIGH,
        confidence=0.9,
    )


class TestSchemaGroundTruthPipeline:
    @pytest.mark.asyncio
    async def test_pass_on_first_round(self, ctx, high_intent):
        valid_output = json.dumps({"answer": "Paris is the capital of France"})
        agent_pool = FakeAgentPool(
            responses=[AgentResult(output=valid_output, task_id="t1", cost=None)]
        )
        pipeline = VerifierPipeline(
            verifiers=[
                SchemaVerifier(required_keys=["answer"]),
                GroundTruthVerifier(reference="Paris", mode="substring"),
            ]
        )
        strategy = EvaluatorOptimizerStrategy(max_rounds=3)
        result = await strategy.execute(high_intent, ctx, agent_pool, pipeline)
        assert result.confidence > 0.0
        assert result.strategy_id == "evaluator_optimizer"

    @pytest.mark.asyncio
    async def test_retries_until_pass(self, ctx, high_intent):
        bad_output = json.dumps({"answer": "wrong answer"})
        good_output = json.dumps({"answer": "Paris is the capital"})
        agent_pool = FakeAgentPool(
            responses=[
                AgentResult(output=bad_output, task_id="t1", cost=None),
                AgentResult(output=good_output, task_id="t2", cost=None),
            ]
        )
        pipeline = VerifierPipeline(
            verifiers=[
                SchemaVerifier(required_keys=["answer"]),
                GroundTruthVerifier(reference="Paris", mode="substring"),
            ]
        )
        strategy = EvaluatorOptimizerStrategy(max_rounds=3)
        result = await strategy.execute(high_intent, ctx, agent_pool, pipeline)
        assert agent_pool.dispatch_count == 2
        assert result.strategy_id == "evaluator_optimizer"

    @pytest.mark.asyncio
    async def test_any_pass_mode_accepts_partial(self, ctx, high_intent):
        output = json.dumps({"answer": "no match here"})
        agent_pool = FakeAgentPool(
            responses=[AgentResult(output=output, task_id="t1", cost=None)]
        )
        pipeline = VerifierPipeline(
            verifiers=[
                SchemaVerifier(required_keys=["answer"]),   # passes (key present)
                GroundTruthVerifier(reference="Paris", mode="substring"),  # fails
            ],
            mode=PipelineMode.ANY_PASS,
        )
        strategy = EvaluatorOptimizerStrategy(max_rounds=3)
        result = await strategy.execute(high_intent, ctx, agent_pool, pipeline)
        assert result.strategy_id == "evaluator_optimizer"
        assert agent_pool.dispatch_count == 1  # passed on first round via ANY_PASS
