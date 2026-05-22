"""Phase 11.z — NeighborGraphBackbone tests.

Verifies neighbor-expansion-mode IKnowledgeBackbone over IGraphStore.
"""

from __future__ import annotations

import pytest

from ryuu_knowledge_base.backbone import BackboneType
from ryuu_knowledge_graph import (
    Edge,
    InMemoryGraphStore,
    NeighborGraphBackbone,
    Node,
)


async def _build_class_graph() -> InMemoryGraphStore:
    """Build small graph: UserController → UserService → UserRepository."""
    store = InMemoryGraphStore()
    await store.upsert_node(Node(
        node_id="UserController",
        labels=["Class"],
        properties={"fqn": "com.app.UserController", "summary": "REST controller"},
    ))
    await store.upsert_node(Node(
        node_id="UserService",
        labels=["Class"],
        properties={"fqn": "com.app.UserService", "summary": "business logic"},
    ))
    await store.upsert_node(Node(
        node_id="UserRepository",
        labels=["Class"],
        properties={"fqn": "com.app.UserRepository", "summary": "data access"},
    ))
    await store.upsert_edge(Edge(src_id="UserController", dst_id="UserService", rel_type="DEPENDS_ON"))
    await store.upsert_edge(Edge(src_id="UserService", dst_id="UserRepository", rel_type="DEPENDS_ON"))
    return store


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_backbone_type_is_graph() -> None:
    assert NeighborGraphBackbone().backbone_type == BackboneType.GRAPH


def test_default_store_is_in_memory() -> None:
    backbone = NeighborGraphBackbone()
    assert isinstance(backbone._store, InMemoryGraphStore)


def test_max_hops_validation() -> None:
    with pytest.raises(ValueError, match="max_hops"):
        NeighborGraphBackbone(max_hops=0)


# ---------------------------------------------------------------------------
# query()
# ---------------------------------------------------------------------------


async def test_query_returns_neighbors_of_known_entity() -> None:
    store = await _build_class_graph()
    backbone = NeighborGraphBackbone(store, max_hops=1)

    result = await backbone.query("UserController", scope_key="proj", top_k=5)
    assert len(result.results) == 1   # UserService is 1-hop neighbor
    assert "UserService" in result.results[0]
    assert result.metadata["entity_id"] == "UserController"
    assert result.metadata["max_hops"] == 1


async def test_query_returns_empty_for_unknown_entity() -> None:
    backbone = NeighborGraphBackbone(InMemoryGraphStore())
    result = await backbone.query("NonExistent", scope_key="proj")
    assert result.results == []
    assert result.scores == []


async def test_query_respects_max_hops_2() -> None:
    store = await _build_class_graph()
    backbone = NeighborGraphBackbone(store, max_hops=2)

    result = await backbone.query("UserController", scope_key="proj", top_k=5)
    # max_hops=2 reaches UserService (1) + UserRepository (2)
    assert len(result.results) == 2
    text = " ".join(result.results)
    assert "UserService" in text
    assert "UserRepository" in text


async def test_query_respects_top_k() -> None:
    store = await _build_class_graph()
    backbone = NeighborGraphBackbone(store, max_hops=2)

    result = await backbone.query("UserController", scope_key="proj", top_k=1)
    assert len(result.results) == 1


# ---------------------------------------------------------------------------
# assemble_context()
# ---------------------------------------------------------------------------


async def test_assemble_context_includes_node_and_neighbors() -> None:
    store = await _build_class_graph()
    backbone = NeighborGraphBackbone(store, max_hops=1)

    ctx = await backbone.assemble_context(
        query="UserController", scope_key="proj", budget_tokens=500,
    )
    assert "UserController" in ctx.text
    assert "UserService" in ctx.text
    assert ctx.token_count > 0
    assert "UserController" in ctx.source_ids
    assert "UserService" in ctx.source_ids


async def test_assemble_context_unknown_entity_returns_empty() -> None:
    backbone = NeighborGraphBackbone(InMemoryGraphStore())
    ctx = await backbone.assemble_context(
        query="Ghost", scope_key="proj", budget_tokens=500,
    )
    assert ctx.text == ""
    assert ctx.token_count == 0
    assert ctx.source_ids == []


async def test_assemble_context_budget_trims_neighbors() -> None:
    """Many neighbors + tight budget → trimmed BFS-first."""
    store = InMemoryGraphStore()
    await store.upsert_node(Node(node_id="hub", labels=["X"], properties={"v": 1}))
    for i in range(20):
        nid = f"n{i}"
        await store.upsert_node(Node(
            node_id=nid, labels=["X"],
            properties={"long_field": "x" * 100},   # verbose properties
        ))
        await store.upsert_edge(Edge(src_id="hub", dst_id=nid, rel_type="REL"))

    backbone = NeighborGraphBackbone(store, max_hops=1)
    ctx = await backbone.assemble_context("hub", scope_key="proj", budget_tokens=20)
    # Should trim — token_count near budget, source_ids smaller than full 20+1
    assert ctx.token_count <= 25  # near budget (with some overshoot OK for first chunk)
    assert len(ctx.source_ids) < 21  # not all 20 neighbors fit


async def test_assemble_context_zero_budget_returns_empty() -> None:
    store = await _build_class_graph()
    backbone = NeighborGraphBackbone(store)
    ctx = await backbone.assemble_context("UserController", scope_key="proj", budget_tokens=0)
    assert ctx.text == ""
    assert ctx.token_count == 0


# ---------------------------------------------------------------------------
# Custom formatter
# ---------------------------------------------------------------------------


async def test_custom_formatter_used() -> None:
    store = await _build_class_graph()

    def domain_formatter(node, neighbors):
        return (
            f"Class {node.properties['fqn']}: {node.properties['summary']}\n"
            f"Depends on: {', '.join(n.properties['fqn'] for n in neighbors)}"
        )

    backbone = NeighborGraphBackbone(store, max_hops=1, formatter=domain_formatter)
    ctx = await backbone.assemble_context("UserController", scope_key="proj", budget_tokens=500)

    assert "com.app.UserController" in ctx.text
    assert "Depends on: com.app.UserService" in ctx.text


# ---------------------------------------------------------------------------
# write()
# ---------------------------------------------------------------------------


async def test_write_creates_observation_node() -> None:
    store = InMemoryGraphStore()
    backbone = NeighborGraphBackbone(store)
    await backbone.write(
        "User authentication flow uses JWT tokens",
        scope_key="proj-1",
        metadata={"phase": "ingestion"},
    )
    # Observation node added
    assert len(store._nodes) == 1
    node = next(iter(store._nodes.values()))
    assert "observation" in node.labels
    assert node.properties["scope"] == "proj-1"
    assert node.properties["phase"] == "ingestion"
    assert "JWT" in node.properties["text"]
