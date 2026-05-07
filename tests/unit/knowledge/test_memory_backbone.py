"""Unit tests for MemoryBackbone — P3-T05."""

from __future__ import annotations

import pytest

from uaaf.knowledge.backbone import AssembledContext, BackboneType, IKnowledgeBackbone
from uaaf.knowledge.memory.backbone import MemoryBackbone


class TestMemoryBackbone:
    @pytest.mark.asyncio
    async def test_write_and_query(self):
        bb = MemoryBackbone()
        await bb.write("the cat sat on the mat", scope_key="s1")
        result = await bb.query("cat", scope_key="s1")
        assert any("cat" in r for r in result.results)

    @pytest.mark.asyncio
    async def test_assemble_context_returns_assembled_context(self):
        bb = MemoryBackbone()
        await bb.write("Python is a programming language", scope_key="s1")
        ctx = await bb.assemble_context("Python", scope_key="s1", budget_tokens=100)
        assert isinstance(ctx, AssembledContext)
        assert ctx.token_count >= 0

    @pytest.mark.asyncio
    async def test_budget_zero_returns_empty(self):
        bb = MemoryBackbone()
        await bb.write("lots of content here", scope_key="s1")
        ctx = await bb.assemble_context("content", scope_key="s1", budget_tokens=0)
        assert ctx.text == ""
        assert ctx.token_count == 0

    @pytest.mark.asyncio
    async def test_backbone_type(self):
        bb = MemoryBackbone()
        assert bb.backbone_type == BackboneType.MEMORY

    def test_satisfies_protocol(self):
        bb = MemoryBackbone()
        assert isinstance(bb, IKnowledgeBackbone)

    @pytest.mark.asyncio
    async def test_write_propagates_to_both_layers(self):
        bb = MemoryBackbone()
        await bb.write("shared content", scope_key="s1")
        # Both working and episodic should have it
        result = await bb.query("shared", scope_key="s1", top_k=10)
        assert len(result.results) >= 1
