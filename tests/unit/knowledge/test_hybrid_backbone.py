"""Unit tests for HybridBackbone — P3-T09."""

from __future__ import annotations

import pytest

from ryuu.knowledge.backbone import AssembledContext, BackboneType, IKnowledgeBackbone
from ryuu.knowledge.hybrid import HybridBackbone


class TestHybridBackbone:
    @pytest.mark.asyncio
    async def test_write_queries_both(self):
        bb = HybridBackbone()
        await bb.write("machine learning concepts", scope_key="s1")
        result = await bb.query("machine", scope_key="s1")
        assert len(result.results) >= 1

    @pytest.mark.asyncio
    async def test_assemble_context(self):
        bb = HybridBackbone()
        await bb.write("deep learning neural networks", scope_key="s1")
        ctx = await bb.assemble_context("deep learning", scope_key="s1", budget_tokens=200)
        assert isinstance(ctx, AssembledContext)

    @pytest.mark.asyncio
    async def test_backbone_type(self):
        bb = HybridBackbone()
        assert bb.backbone_type == BackboneType.HYBRID

    def test_satisfies_protocol(self):
        bb = HybridBackbone()
        assert isinstance(bb, IKnowledgeBackbone)

    @pytest.mark.asyncio
    async def test_dedup_results(self):
        bb = HybridBackbone()
        await bb.write("unique content", scope_key="s1")
        result = await bb.query("unique", scope_key="s1", top_k=10)
        # Should not return the same string twice
        assert len(result.results) == len(set(result.results))
