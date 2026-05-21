"""Smoke tests for ryuu-knowledge-base, memory, graph, and knowledge packages."""
from __future__ import annotations

import pytest


# --- ryuu-knowledge-base ---

def test_backbone_types_importable() -> None:
    from ryuu_knowledge_base.backbone import AssembledContext, BackboneType, IKnowledgeBackbone, QueryResult
    assert BackboneType.MEMORY == "memory"
    assert BackboneType.GRAPH == "graph"
    assert BackboneType.HYBRID == "hybrid"


def test_query_result_construction() -> None:
    from ryuu_knowledge_base.backbone import QueryResult
    r = QueryResult(results=["a", "b"], scores=[0.9, 0.7])
    assert r.results == ["a", "b"]
    assert r.scores == [0.9, 0.7]
    assert r.metadata == {}


def test_assembled_context_construction() -> None:
    from ryuu_knowledge_base.backbone import AssembledContext
    ctx = AssembledContext(text="hello world", token_count=2, source_ids=["x:0"])
    assert ctx.text == "hello world"
    assert ctx.token_count == 2


def test_context_assembler_delegates() -> None:
    from ryuu_knowledge_base.backbone import AssembledContext, BackboneType, QueryResult
    from ryuu_knowledge_base.context_assembler import ContextAssembler

    class FakeBackbone:
        backbone_type = BackboneType.MEMORY
        async def write(self, observation, scope_key, metadata=None): pass
        async def query(self, query, scope_key, top_k=5): return QueryResult([], [])
        async def assemble_context(self, query, scope_key, budget_tokens=2000):
            return AssembledContext(text="fake", token_count=1)

    assembler = ContextAssembler(FakeBackbone())
    assert assembler is not None


# --- ryuu-knowledge-memory ---

def test_memory_layer_enum() -> None:
    from ryuu_knowledge_memory.store import MemoryLayer
    assert MemoryLayer.WORKING == "working"
    assert MemoryLayer.EPISODIC == "episodic"


def test_memory_entry_defaults() -> None:
    from ryuu_knowledge_memory.store import MemoryEntry
    e = MemoryEntry(content="hello")
    assert e.content == "hello"
    assert e.score == 1.0
    assert isinstance(e.created_at, float)


async def test_working_memory_store_fifo() -> None:
    from ryuu_knowledge_memory.working import WorkingMemoryStore
    store = WorkingMemoryStore(max_entries=2)
    await store.store("a", "s1")
    await store.store("b", "s1")
    await store.store("c", "s1")  # evicts "a"
    entries = await store.retrieve("", "s1", top_k=5)
    texts = [e.content for e in entries]
    assert "a" not in texts
    assert "c" in texts


async def test_episodic_memory_keyword_score() -> None:
    from ryuu_knowledge_memory.episodic import EpisodicMemoryStore
    store = EpisodicMemoryStore()
    await store.store("python programming language", "s1")
    await store.store("java enterprise application", "s1")
    results = await store.retrieve("python language", "s1", top_k=5)
    assert results[0].content == "python programming language"


async def test_memory_backbone_write_and_query() -> None:
    from ryuu_knowledge_memory.backbone import MemoryBackbone
    b = MemoryBackbone()
    await b.write("the quick brown fox", "u1")
    result = await b.query("quick fox", "u1", top_k=3)
    assert len(result.results) >= 1
    assert result.results[0] == "the quick brown fox"


async def test_memory_backbone_assemble_context() -> None:
    from ryuu_knowledge_memory.backbone import MemoryBackbone
    b = MemoryBackbone()
    await b.write("hello world test", "u1")
    ctx = await b.assemble_context("hello", "u1", budget_tokens=100)
    assert "hello" in ctx.text
    assert ctx.token_count > 0


# --- ryuu-knowledge-graph ---

def test_node_edge_importable() -> None:
    from ryuu_knowledge_graph.store import Edge, IGraphStore, Node
    n = Node(node_id="n1", labels=["person"], properties={"name": "Alice"})
    assert n.node_id == "n1"
    e = Edge(src_id="n1", dst_id="n2", rel_type="KNOWS")
    assert e.rel_type == "KNOWS"


async def test_in_memory_graph_store_upsert_search() -> None:
    from ryuu_knowledge_graph.in_memory import InMemoryGraphStore
    from ryuu_knowledge_graph.store import Node
    store = InMemoryGraphStore()
    await store.upsert_node(Node(node_id="n1", properties={"name": "Alice"}))
    found = await store.text_search("alice", top_k=5)
    assert len(found) == 1
    assert found[0].node_id == "n1"


async def test_graph_backbone_write_and_query() -> None:
    from ryuu_knowledge_graph.backbone import GraphBackbone
    b = GraphBackbone()
    await b.write("the sky is blue", "u1")
    result = await b.query("sky", "u1", top_k=5)
    assert "the sky is blue" in result.results


async def test_graph_backbone_assemble_context() -> None:
    from ryuu_knowledge_graph.backbone import GraphBackbone
    b = GraphBackbone()
    await b.write("rain falls from clouds", "u1")
    ctx = await b.assemble_context("rain", "u1", budget_tokens=50)
    assert ctx.token_count >= 0


# --- ryuu-knowledge (hybrid) ---

async def test_hybrid_backbone_combines_both() -> None:
    from ryuu_knowledge.hybrid import HybridBackbone
    h = HybridBackbone()
    await h.write("hybrid observation text", "u1")
    result = await h.query("hybrid observation", "u1", top_k=5)
    assert any("hybrid" in r for r in result.results)


async def test_hybrid_backbone_assemble_budget_split() -> None:
    from ryuu_knowledge.hybrid import HybridBackbone
    h = HybridBackbone()
    await h.write("budget split test content here", "u1")
    ctx = await h.assemble_context("budget split", "u1", budget_tokens=200)
    assert ctx.token_count >= 0


async def test_hybrid_backbone_zero_budget() -> None:
    from ryuu_knowledge.hybrid import HybridBackbone
    h = HybridBackbone()
    ctx = await h.assemble_context("anything", "u1", budget_tokens=0)
    assert ctx.text == ""
    assert ctx.token_count == 0


def test_hybrid_backbone_type() -> None:
    from ryuu_knowledge.hybrid import HybridBackbone
    from ryuu_knowledge_base.backbone import BackboneType
    assert HybridBackbone.backbone_type == BackboneType.HYBRID
