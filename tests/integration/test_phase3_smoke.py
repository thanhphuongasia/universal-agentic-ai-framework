"""Phase 3 integration smoke — EvaluatorOptimizerStrategy + ContextAssembler."""

from __future__ import annotations

import json

import pytest

from uaaf._testing.fakes import FakeAgentPool
from uaaf.cognitive.strategies.evaluator_optimizer import EvaluatorOptimizerStrategy
from uaaf.cognitive.verifiers.schema import SchemaVerifier
from uaaf.execution.agent import AgentResult
from uaaf.intent.models import ComplexityLevel, StructuredIntent
from uaaf.knowledge.context_assembler import ContextAssembler
from uaaf.knowledge.hybrid import HybridBackbone
from uaaf.knowledge.memory.backbone import MemoryBackbone
from uaaf_workflow.context import ContextScope, ExecutionContext


@pytest.fixture()
def ctx() -> ExecutionContext:
    return ExecutionContext(
        scope=ContextScope(user_id="u1", session_id="s1", domain="test"),
        correlation_id="c1",
    )


@pytest.fixture()
def high_intent() -> StructuredIntent:
    return StructuredIntent(
        intent_type="summarize",
        action="generate_summary",
        entities={"topic": "Python"},
        complexity=ComplexityLevel.HIGH,
        confidence=0.9,
    )


class TestMemoryBackboneWithStrategy:
    @pytest.mark.asyncio
    async def test_assemble_context_then_execute(self, ctx, high_intent):
        backbone = MemoryBackbone()
        assembler = ContextAssembler(backbone)

        await assembler.write("Python is a high-level programming language.", scope_key="s1")
        await assembler.write("Python supports async/await for concurrency.", scope_key="s1")

        assembled = await assembler.assemble("Python", scope_key="s1", budget_tokens=200)
        assert "Python" in assembled.text

        output = json.dumps({"summary": "Python is great"})
        pool = FakeAgentPool(responses=[AgentResult(output=output, task_id="t1", cost=None)])
        verifier = SchemaVerifier(required_keys=["summary"])
        strategy = EvaluatorOptimizerStrategy(max_rounds=2)
        result = await strategy.execute(high_intent, ctx, pool, verifier)
        assert result.strategy_id == "evaluator_optimizer"


class TestHybridBackboneSmoke:
    @pytest.mark.asyncio
    async def test_write_query_assemble(self, ctx):
        backbone = HybridBackbone()
        assembler = ContextAssembler(backbone)

        await assembler.write("FastAPI is a modern Python web framework.", scope_key="s1")
        assembled = await assembler.assemble("FastAPI", scope_key="s1", budget_tokens=200)
        assert isinstance(assembled.text, str)
        assert assembled.token_count >= 0

    @pytest.mark.asyncio
    async def test_query_merges_both_sources(self):
        backbone = HybridBackbone()
        await backbone.write("graph source data", scope_key="s1")
        result = await backbone.query("graph source", scope_key="s1", top_k=10)
        assert len(result.results) >= 1
