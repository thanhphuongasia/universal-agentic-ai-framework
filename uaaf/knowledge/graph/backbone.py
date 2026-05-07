"""GraphBackbone — IKnowledgeBackbone backed by IGraphStore — P3-T08."""

from __future__ import annotations

import uuid
from typing import Any

from uaaf.knowledge.backbone import AssembledContext, BackboneType, QueryResult
from uaaf.knowledge.graph.in_memory import InMemoryGraphStore
from uaaf.knowledge.graph.store import IGraphStore, Node


def _token_count(text: str) -> int:
    return len(text.split())


class GraphBackbone:
    """Knowledge backbone using a graph store for structured retrieval."""

    backbone_type = BackboneType.GRAPH

    def __init__(self, store: IGraphStore | None = None) -> None:
        self._store: IGraphStore = store or InMemoryGraphStore()

    async def write(
        self,
        observation: str,
        scope_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        node = Node(
            node_id=str(uuid.uuid4()),
            labels=["observation"],
            properties={"text": observation, "scope": scope_key, **(metadata or {})},
        )
        await self._store.upsert_node(node)

    async def query(
        self,
        query: str,
        scope_key: str,
        top_k: int = 5,
    ) -> QueryResult:
        nodes = await self._store.text_search(query, top_k=top_k)
        results = [n.properties.get("text", n.node_id) for n in nodes]
        scores = [1.0] * len(results)
        return QueryResult(results=results, scores=scores)

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
        source_ids: list[str] = []

        for i, text in enumerate(result.results):
            tc = _token_count(text)
            if tokens_used + tc > budget_tokens:
                break
            parts.append(text)
            tokens_used += tc
            source_ids.append(f"graph:{i}")

        assembled = "\n".join(parts)
        return AssembledContext(
            text=assembled,
            token_count=_token_count(assembled),
            source_ids=source_ids,
        )
