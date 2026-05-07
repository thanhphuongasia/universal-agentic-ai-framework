"""Unit tests for GraphBackbone — P3-T08."""

from __future__ import annotations

import pytest

from uaaf.knowledge.backbone import AssembledContext, BackboneType, IKnowledgeBackbone
from uaaf.knowledge.graph.backbone import GraphBackbone


class TestGraphBackbone:
    @pytest.mark.asyncio
    async def test_write_and_query(self):
        bb = GraphBackbone()
        await bb.write("Python language features", scope_key="s1")
        result = await bb.query("Python", scope_key="s1")
        assert any("Python" in r for r in result.results)

    @pytest.mark.asyncio
    async def test_assemble_context(self):
        bb = GraphBackbone()
        await bb.write("FastAPI web framework", scope_key="s1")
        ctx = await bb.assemble_context("FastAPI", scope_key="s1", budget_tokens=100)
        assert isinstance(ctx, AssembledContext)

    @pytest.mark.asyncio
    async def test_backbone_type(self):
        bb = GraphBackbone()
        assert bb.backbone_type == BackboneType.GRAPH

    def test_satisfies_protocol(self):
        bb = GraphBackbone()
        assert isinstance(bb, IKnowledgeBackbone)

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self):
        bb = GraphBackbone()
        result = await bb.query("nonexistent", scope_key="s1")
        assert result.results == []
        assert result.scores == []
