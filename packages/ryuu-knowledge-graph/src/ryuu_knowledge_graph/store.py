from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class Node:
    node_id: str
    labels: list[str] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class Edge:
    src_id: str
    dst_id: str
    rel_type: str
    properties: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class IGraphStore(Protocol):
    async def upsert_node(self, node: Node) -> None: ...
    async def upsert_edge(self, edge: Edge) -> None: ...
    async def get_node(self, node_id: str) -> Node | None: ...
    async def get_neighbors(self, node_id: str, max_hops: int = 1) -> list[Node]: ...
    async def text_search(self, query: str, top_k: int = 5) -> list[Node]: ...
