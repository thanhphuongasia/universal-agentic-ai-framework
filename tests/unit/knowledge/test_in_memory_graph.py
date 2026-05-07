"""Unit tests for InMemoryGraphStore — P3-T07."""

from __future__ import annotations

import pytest

from uaaf.knowledge.graph.in_memory import InMemoryGraphStore
from uaaf.knowledge.graph.store import Edge, Node


class TestInMemoryGraphStore:
    @pytest.mark.asyncio
    async def test_upsert_and_get_node(self):
        store = InMemoryGraphStore()
        node = Node(node_id="n1", labels=["Person"], properties={"name": "Alice"})
        await store.upsert_node(node)
        result = await store.get_node("n1")
        assert result is not None
        assert result.node_id == "n1"

    @pytest.mark.asyncio
    async def test_get_nonexistent_node_returns_none(self):
        store = InMemoryGraphStore()
        result = await store.get_node("missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_upsert_overwrites(self):
        store = InMemoryGraphStore()
        await store.upsert_node(Node(node_id="n1", labels=["A"], properties={"v": 1}))
        await store.upsert_node(Node(node_id="n1", labels=["B"], properties={"v": 2}))
        result = await store.get_node("n1")
        assert result is not None
        assert result.properties["v"] == 2

    @pytest.mark.asyncio
    async def test_get_neighbors_direct(self):
        store = InMemoryGraphStore()
        await store.upsert_node(Node(node_id="a", labels=[], properties={}))
        await store.upsert_node(Node(node_id="b", labels=[], properties={}))
        await store.upsert_edge(Edge(src_id="a", dst_id="b", rel_type="KNOWS", properties={}))
        neighbors = await store.get_neighbors("a", max_hops=1)
        ids = {n.node_id for n in neighbors}
        assert "b" in ids

    @pytest.mark.asyncio
    async def test_get_neighbors_multi_hop(self):
        store = InMemoryGraphStore()
        for nid in ["a", "b", "c"]:
            await store.upsert_node(Node(node_id=nid, labels=[], properties={}))
        await store.upsert_edge(Edge(src_id="a", dst_id="b", rel_type="X", properties={}))
        await store.upsert_edge(Edge(src_id="b", dst_id="c", rel_type="X", properties={}))
        neighbors = await store.get_neighbors("a", max_hops=2)
        ids = {n.node_id for n in neighbors}
        assert "b" in ids and "c" in ids

    @pytest.mark.asyncio
    async def test_text_search(self):
        store = InMemoryGraphStore()
        await store.upsert_node(Node(node_id="n1", labels=["Func"], properties={"name": "parse_json"}))
        await store.upsert_node(Node(node_id="n2", labels=["Func"], properties={"name": "render_html"}))
        results = await store.text_search("parse", top_k=5)
        assert any(n.node_id == "n1" for n in results)
        assert all(n.node_id != "n2" for n in results)

    @pytest.mark.asyncio
    async def test_text_search_top_k(self):
        store = InMemoryGraphStore()
        for i in range(5):
            await store.upsert_node(Node(node_id=f"n{i}", labels=[], properties={"text": "match"}))
        results = await store.text_search("match", top_k=3)
        assert len(results) == 3
