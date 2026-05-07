"""MemoryBackbone — IKnowledgeBackbone backed by memory layers — P3-T05."""

from __future__ import annotations

from typing import Any

from uaaf.knowledge.backbone import AssembledContext, BackboneType, QueryResult
from uaaf.knowledge.memory.episodic import EpisodicMemoryStore
from uaaf.knowledge.memory.store import IMemoryStore
from uaaf.knowledge.memory.working import WorkingMemoryStore


def _token_count(text: str) -> int:
    return len(text.split())


class MemoryBackbone:
    """Combines working + episodic memory layers into an IKnowledgeBackbone."""

    backbone_type = BackboneType.MEMORY

    def __init__(self, layers: list[IMemoryStore] | None = None) -> None:
        self._layers: list[IMemoryStore] = layers or [
            WorkingMemoryStore(),
            EpisodicMemoryStore(),
        ]

    async def write(
        self,
        observation: str,
        scope_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        for layer in self._layers:
            await layer.store(observation, scope_key, metadata)

    async def query(
        self,
        query: str,
        scope_key: str,
        top_k: int = 5,
    ) -> QueryResult:
        seen: set[str] = set()
        merged: list[tuple[str, float]] = []
        for layer in self._layers:
            entries = await layer.retrieve(query, scope_key, top_k)
            for e in entries:
                if e.content not in seen:
                    seen.add(e.content)
                    merged.append((e.content, e.score))
        merged.sort(key=lambda x: x[1], reverse=True)
        top = merged[:top_k]
        return QueryResult(
            results=[t[0] for t in top],
            scores=[t[1] for t in top],
        )

    async def assemble_context(
        self,
        query: str,
        scope_key: str,
        budget_tokens: int = 2000,
    ) -> AssembledContext:
        if budget_tokens <= 0:
            return AssembledContext(text="", token_count=0)

        result = await self.query(query, scope_key, top_k=20)
        parts: list[str] = []
        tokens_used = 0
        for text in result.results:
            tc = _token_count(text)
            if tokens_used + tc > budget_tokens:
                break
            parts.append(text)
            tokens_used += tc

        assembled = "\n".join(parts)
        return AssembledContext(
            text=assembled,
            token_count=_token_count(assembled),
            source_ids=[f"memory:{i}" for i in range(len(parts))],
        )
