"""ryuu-knowledge-graph — IGraphStore Protocol + IKnowledgeBackbone variants.

Public API:

    # Core types
    from ryuu_knowledge_graph import Node, Edge, IGraphStore

    # Reference impl (testing / single-process)
    from ryuu_knowledge_graph import InMemoryGraphStore

    # IKnowledgeBackbone variants
    from ryuu_knowledge_graph import GraphBackbone, NeighborGraphBackbone

GraphBackbone vs NeighborGraphBackbone:
  - GraphBackbone.query()        → text_search(query) — semantic match over node properties
  - NeighborGraphBackbone.query() → get_neighbors(entity_id) — N-hop graph expansion

Production: implement IGraphStore for your DB (Neo4j, Memgraph, ArangoDB).
"""

from __future__ import annotations

from ryuu_knowledge_graph.backbone import GraphBackbone
from ryuu_knowledge_graph.in_memory import InMemoryGraphStore
from ryuu_knowledge_graph.neighbor_backbone import NeighborGraphBackbone
from ryuu_knowledge_graph.store import Edge, IGraphStore, Node

__all__ = [
    "Edge",
    "GraphBackbone",
    "IGraphStore",
    "InMemoryGraphStore",
    "NeighborGraphBackbone",
    "Node",
]
