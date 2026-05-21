"""Unit tests for ContextAssembler — P3-T10."""

from __future__ import annotations

import pytest

from ryuu.knowledge.backbone import AssembledContext
from ryuu.knowledge.context_assembler import ContextAssembler
from ryuu.knowledge.memory.backbone import MemoryBackbone


class TestContextAssembler:
    @pytest.mark.asyncio
    async def test_write_and_assemble(self):
        backbone = MemoryBackbone()
        assembler = ContextAssembler(backbone)
        await assembler.write("Python is great for data science", scope_key="s1")
        ctx = await assembler.assemble("Python", scope_key="s1", budget_tokens=100)
        assert isinstance(ctx, AssembledContext)
        assert "Python" in ctx.text

    @pytest.mark.asyncio
    async def test_delegates_to_backbone(self):
        backbone = MemoryBackbone()
        assembler = ContextAssembler(backbone)
        await backbone.write("direct backbone write", scope_key="s1")
        ctx = await assembler.assemble("backbone", scope_key="s1", budget_tokens=100)
        assert "backbone" in ctx.text

    @pytest.mark.asyncio
    async def test_zero_budget_returns_empty(self):
        backbone = MemoryBackbone()
        assembler = ContextAssembler(backbone)
        await assembler.write("some data", scope_key="s1")
        ctx = await assembler.assemble("data", scope_key="s1", budget_tokens=0)
        assert ctx.text == ""
        assert ctx.token_count == 0
