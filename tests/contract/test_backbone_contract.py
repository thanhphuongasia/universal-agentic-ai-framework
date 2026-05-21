"""Contract tests — every IKnowledgeBackbone must satisfy the protocol shape."""

from __future__ import annotations

import pytest

from ryuu._testing.fakes import FakeKnowledgeBackbone
from ryuu.knowledge.backbone import AssembledContext, IKnowledgeBackbone, QueryResult
from ryuu.knowledge.graph.backbone import GraphBackbone
from ryuu.knowledge.hybrid import HybridBackbone
from ryuu.knowledge.memory.backbone import MemoryBackbone


@pytest.fixture(
    params=[
        pytest.param("memory", id="memory"),
        pytest.param("graph", id="graph"),
        pytest.param("hybrid", id="hybrid"),
        pytest.param("fake", id="fake"),
    ]
)
def backbone(request: pytest.FixtureRequest) -> IKnowledgeBackbone:
    name = request.param
    if name == "memory":
        return MemoryBackbone()
    if name == "graph":
        return GraphBackbone()
    if name == "hybrid":
        return HybridBackbone()
    return FakeKnowledgeBackbone()


class TestBackboneContract:
    def test_has_backbone_type(self, backbone: IKnowledgeBackbone):
        assert backbone.backbone_type is not None

    def test_is_iknowledgebackbone(self, backbone: IKnowledgeBackbone):
        assert isinstance(backbone, IKnowledgeBackbone)

    @pytest.mark.asyncio
    async def test_write_does_not_raise(self, backbone: IKnowledgeBackbone):
        await backbone.write("test observation", scope_key="test")

    @pytest.mark.asyncio
    async def test_query_returns_query_result(self, backbone: IKnowledgeBackbone):
        await backbone.write("searchable content", scope_key="test")
        result = await backbone.query("searchable", scope_key="test")
        assert isinstance(result, QueryResult)
        assert isinstance(result.results, list)
        assert isinstance(result.scores, list)
        assert len(result.results) == len(result.scores)

    @pytest.mark.asyncio
    async def test_assemble_context_returns_assembled_context(self, backbone: IKnowledgeBackbone):
        await backbone.write("Python programming language", scope_key="test")
        ctx = await backbone.assemble_context("Python", scope_key="test", budget_tokens=500)
        assert isinstance(ctx, AssembledContext)
        assert isinstance(ctx.text, str)
        assert isinstance(ctx.token_count, int)
        assert ctx.token_count >= 0

    @pytest.mark.asyncio
    async def test_write_accepts_metadata(self, backbone: IKnowledgeBackbone):
        await backbone.write("annotated content", scope_key="test", metadata={"tag": "unit-test"})

    @pytest.mark.asyncio
    async def test_zero_budget_returns_empty_context(self, backbone: IKnowledgeBackbone):
        await backbone.write("some content", scope_key="test")
        ctx = await backbone.assemble_context("some", scope_key="test", budget_tokens=0)
        assert ctx.text == ""
        assert ctx.token_count == 0
