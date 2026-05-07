"""HybridBackbone — combines GraphBackbone (primary) + MemoryBackbone (secondary) — P3-T09."""

from __future__ import annotations

from typing import Any

from uaaf.knowledge.backbone import AssembledContext, BackboneType, IKnowledgeBackbone, QueryResult
from uaaf.knowledge.graph.backbone import GraphBackbone
from uaaf.knowledge.memory.backbone import MemoryBackbone


def _token_count(text: str) -> int:
    return len(text.split())


class HybridBackbone:
    """Merges graph and memory retrieval with configurable budget split."""

    backbone_type = BackboneType.HYBRID

    def __init__(
        self,
        primary: IKnowledgeBackbone | None = None,
        secondary: IKnowledgeBackbone | None = None,
    ) -> None:
        self._primary: IKnowledgeBackbone = primary or GraphBackbone()
        self._secondary: IKnowledgeBackbone = secondary or MemoryBackbone()

    async def write(
        self,
        observation: str,
        scope_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self._primary.write(observation, scope_key, metadata)
        await self._secondary.write(observation, scope_key, metadata)

    async def query(
        self,
        query: str,
        scope_key: str,
        top_k: int = 5,
    ) -> QueryResult:
        p_result = await self._primary.query(query, scope_key, top_k)
        s_result = await self._secondary.query(query, scope_key, top_k)

        seen: set[str] = set()
        merged: list[tuple[str, float]] = []
        for text, score in zip(p_result.results, p_result.scores, strict=False):
            if text not in seen:
                seen.add(text)
                merged.append((text, score))
        for text, score in zip(s_result.results, s_result.scores, strict=False):
            if text not in seen:
                seen.add(text)
                merged.append((text, score))

        merged.sort(key=lambda x: x[1], reverse=True)
        top = merged[:top_k]
        return QueryResult(results=[t[0] for t in top], scores=[t[1] for t in top])

    async def assemble_context(
        self,
        query: str,
        scope_key: str,
        budget_tokens: int = 2000,
    ) -> AssembledContext:
        if budget_tokens <= 0:
            return AssembledContext(text="", token_count=0)

        primary_budget = int(budget_tokens * 0.6)
        secondary_budget = budget_tokens - primary_budget

        p_ctx = await self._primary.assemble_context(query, scope_key, primary_budget)
        s_ctx = await self._secondary.assemble_context(query, scope_key, secondary_budget)

        parts = [t for t in [p_ctx.text, s_ctx.text] if t]
        assembled = "\n".join(parts)
        return AssembledContext(
            text=assembled,
            token_count=_token_count(assembled),
            source_ids=p_ctx.source_ids + s_ctx.source_ids,
        )
