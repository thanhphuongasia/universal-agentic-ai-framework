from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from ryuu_knowledge_base.backbone import AssembledContext, BackboneType, QueryResult
from ryuu_knowledge_memory.episodic import EpisodicMemoryStore
from ryuu_knowledge_memory.store import IMemoryStore, MemoryLayer
from ryuu_knowledge_memory.working import WorkingMemoryStore

if TYPE_CHECKING:
    from ryuu_knowledge_memory.consolidator import DreamingConsolidator, ExtractionFilter


def _token_count(text: str) -> int:
    return len(text.split())


class MemoryBackbone:
    backbone_type = BackboneType.MEMORY

    def __init__(
        self,
        layers: list[IMemoryStore] | None = None,
        processor: ExtractionFilter | None = None,
        dreaming_consolidator: DreamingConsolidator | None = None,
    ) -> None:
        self._layers: list[IMemoryStore] = layers or [
            WorkingMemoryStore(),
            EpisodicMemoryStore(),
        ]
        self._processor = processor
        self._dreamer = dreaming_consolidator

    async def write(
        self,
        observation: str,
        scope_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        meta = metadata or {}

        # Working memory: always sync, no filtering
        for layer in self._layers:
            if layer.layer == MemoryLayer.WORKING:
                await layer.store(observation, scope_key, meta)

        # Episodic: run through extraction filter async (non-blocking)
        for layer in self._layers:
            if layer.layer == MemoryLayer.EPISODIC:
                if self._processor is not None:
                    asyncio.ensure_future(
                        self._filtered_episodic_write(layer, observation, scope_key, meta)
                    )
                else:
                    await layer.store(observation, scope_key, meta)

    async def _filtered_episodic_write(
        self,
        layer: IMemoryStore,
        observation: str,
        scope_key: str,
        metadata: dict[str, Any],
    ) -> None:
        assert self._processor is not None
        should_store, content, importance = await self._processor.process(observation)
        if should_store:
            await layer.store(content, scope_key, {**metadata, "importance": importance})

    async def end_session(self, scope_key: str) -> None:
        """Call when a user session ends to trigger async dreaming + eviction."""
        if self._dreamer is not None:
            asyncio.ensure_future(self._dreamer.run_cycle(scope_key))

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
