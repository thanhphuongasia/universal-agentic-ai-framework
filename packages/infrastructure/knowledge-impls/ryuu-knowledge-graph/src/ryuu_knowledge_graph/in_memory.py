from __future__ import annotations

from collections import deque

from ryuu_knowledge_graph.store import Edge, Node


class InMemoryGraphStore:
    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}
        self._edges: list[Edge] = []

    async def upsert_node(self, node: Node) -> None:
        self._nodes[node.node_id] = node

    async def upsert_edge(self, edge: Edge) -> None:
        self._edges.append(edge)

    async def get_node(self, node_id: str) -> Node | None:
        return self._nodes.get(node_id)

    async def get_neighbors(self, node_id: str, max_hops: int = 1) -> list[Node]:
        visited: set[str] = {node_id}
        frontier: deque[tuple[str, int]] = deque([(node_id, 0)])
        result: list[Node] = []

        while frontier:
            current_id, depth = frontier.popleft()
            if depth >= max_hops:
                continue
            for edge in self._edges:
                neighbor_id: str | None = None
                if edge.src_id == current_id:
                    neighbor_id = edge.dst_id
                elif edge.dst_id == current_id:
                    neighbor_id = edge.src_id
                if neighbor_id and neighbor_id not in visited:
                    visited.add(neighbor_id)
                    node = self._nodes.get(neighbor_id)
                    if node:
                        result.append(node)
                    frontier.append((neighbor_id, depth + 1))

        return result

    async def text_search(self, query: str, top_k: int = 5) -> list[Node]:
        q = query.lower()
        matches: list[Node] = []
        for node in self._nodes.values():
            haystack = node.node_id.lower() + " " + " ".join(
                str(v).lower() for v in node.properties.values()
            )
            if q in haystack:
                matches.append(node)
            if len(matches) >= top_k:
                break
        return matches
