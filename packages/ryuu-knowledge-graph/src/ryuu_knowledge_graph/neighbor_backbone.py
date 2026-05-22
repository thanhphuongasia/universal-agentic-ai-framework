"""NeighborGraphBackbone — IKnowledgeBackbone via neighbor expansion. Phase 11.z.

Complements GraphBackbone (text_search mode). Use when caller already knows
the entity ID and wants its graph context (N-hop neighbors), not semantic
similarity over node properties.

Generic across any IGraphStore impl (InMemoryGraphStore reference; production
adapters for Neo4j, Memgraph, ArangoDB, NebulaGraph implement IGraphStore).

Pattern source: code analysis (1-hop class neighbors as ReAct context),
knowledge graphs (entity + related concepts), social/citation networks (author
+ co-authors), recommendation systems (product + bought-together).

Example::

    from ryuu_knowledge_graph import NeighborGraphBackbone, InMemoryGraphStore, Node, Edge

    store = InMemoryGraphStore()
    await store.upsert_node(Node(node_id="UserController", labels=["Class"],
                                 properties={"fqn": "com.app.UserController"}))
    await store.upsert_node(Node(node_id="UserService", labels=["Class"]))
    await store.upsert_edge(Edge(src_id="UserController", dst_id="UserService",
                                 rel_type="DEPENDS_ON"))

    backbone = NeighborGraphBackbone(store, max_hops=1)
    ctx = await backbone.assemble_context(
        query="UserController",  # entity_id (known)
        scope_key="my-project",
        budget_tokens=500,
    )
    # ctx.text contains: node properties + 1-hop neighbors as formatted text
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from ryuu_knowledge_base.backbone import (
    AssembledContext,
    BackboneType,
    QueryResult,
)

from ryuu_knowledge_graph.in_memory import InMemoryGraphStore
from ryuu_knowledge_graph.store import Edge, IGraphStore, Node


def _token_count(text: str) -> int:
    """Rough token estimate — 1 word ≈ 1 token. Production: use tiktoken."""
    return len(text.split())


def _default_formatter(node: Node, neighbors: list[Node]) -> str:
    """Default text format: node properties + each neighbor's label/id/props.

    Override via ``formatter=`` kwarg for domain-specific rendering
    (e.g. code analysis class summaries, social network bios).
    """
    labels = "/".join(node.labels) if node.labels else "Node"
    parts = [f"{labels} '{node.node_id}': {node.properties}"]
    if neighbors:
        parts.append("Neighbors:")
        for n in neighbors:
            n_labels = "/".join(n.labels) if n.labels else "Node"
            parts.append(f"  - {n_labels} '{n.node_id}': {n.properties}")
    return "\n".join(parts)


class NeighborGraphBackbone:
    """IKnowledgeBackbone via N-hop neighbor expansion from a known entity ID.

    Args:
        store: IGraphStore impl (InMemoryGraphStore default for testing).
        max_hops: how many hops out from query entity (1 = direct neighbors).
        formatter: callable ``(node, neighbors) -> str`` for text rendering.
            Override for domain-specific format (default = labels + properties).

    Differs from GraphBackbone:
      - GraphBackbone.query() does ``text_search(query)`` — semantic match
      - NeighborGraphBackbone.query() treats query as entity_id, returns neighbors

    Scope_key semantics:
      - ``write()``: tag observation node with scope_key in properties
      - ``query()`` / ``assemble_context()``: scope_key is informational only
        (graph stores don't natively partition). Use multiple stores for hard
        isolation across tenants.
    """

    backbone_type = BackboneType.GRAPH

    def __init__(
        self,
        store: IGraphStore | None = None,
        max_hops: int = 1,
        formatter: Callable[[Node, list[Node]], str] | None = None,
    ) -> None:
        if max_hops < 1:
            raise ValueError(f"max_hops must be >= 1, got {max_hops}")
        self._store: IGraphStore = store or InMemoryGraphStore()
        self._max_hops = max_hops
        self._formatter = formatter or _default_formatter

    async def write(
        self,
        observation: str,
        scope_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add observation as a graph node, tagged with scope_key + metadata.

        Note: this creates an isolated node (no edges to existing graph). Use
        upstream `IGraphStore.upsert_edge` to wire it in if needed.
        """
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
        """Treat ``query`` as entity_id, return ``top_k`` neighbors as texts.

        If the entity doesn't exist, returns empty QueryResult.
        """
        node = await self._store.get_node(query)
        if node is None:
            return QueryResult(results=[], scores=[])

        neighbors = await self._store.get_neighbors(query, max_hops=self._max_hops)
        # Trim to top_k (preserve order — IGraphStore returns BFS order)
        neighbors = neighbors[:top_k]
        texts = [
            f"{'/'.join(n.labels) if n.labels else 'Node'} '{n.node_id}': {n.properties}"
            for n in neighbors
        ]
        scores = [1.0] * len(texts)   # neighbor-based has no similarity score
        return QueryResult(
            results=texts,
            scores=scores,
            metadata={"entity_id": query, "max_hops": self._max_hops, "node_found": True},
        )

    async def assemble_context(
        self,
        query: str,
        scope_key: str,
        budget_tokens: int = 2000,
    ) -> AssembledContext:
        """Build a formatted context block: entity + neighbors, within budget.

        If entity not found, returns empty AssembledContext.
        Truncation: if formatted text exceeds budget, neighbors trimmed
        breadth-first until fits.
        """
        if budget_tokens <= 0:
            return AssembledContext(text="", token_count=0)

        node = await self._store.get_node(query)
        if node is None:
            return AssembledContext(text="", token_count=0)

        neighbors = await self._store.get_neighbors(query, max_hops=self._max_hops)

        # Format with all neighbors; if exceeds budget, trim
        text = self._formatter(node, neighbors)
        if _token_count(text) <= budget_tokens:
            return AssembledContext(
                text=text,
                token_count=_token_count(text),
                source_ids=[query] + [n.node_id for n in neighbors],
            )

        # Trim neighbors progressively until fits
        for cutoff in range(len(neighbors) - 1, -1, -1):
            trimmed = neighbors[:cutoff]
            text = self._formatter(node, trimmed)
            if _token_count(text) <= budget_tokens:
                return AssembledContext(
                    text=text,
                    token_count=_token_count(text),
                    source_ids=[query] + [n.node_id for n in trimmed],
                )

        # Even node-only exceeds budget — return node-only anyway (best effort)
        text = self._formatter(node, [])
        return AssembledContext(
            text=text,
            token_count=_token_count(text),
            source_ids=[query],
        )


__all__ = ["NeighborGraphBackbone"]
