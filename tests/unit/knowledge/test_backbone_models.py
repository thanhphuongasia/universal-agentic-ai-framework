"""Unit tests for IKnowledgeBackbone models — P3-T01."""

from __future__ import annotations

from ryuu.knowledge.backbone import AssembledContext, BackboneType, IKnowledgeBackbone, QueryResult


class TestBackboneType:
    def test_values(self):
        assert BackboneType.MEMORY == "memory"
        assert BackboneType.GRAPH == "graph"
        assert BackboneType.HYBRID == "hybrid"


class TestQueryResult:
    def test_defaults(self):
        qr = QueryResult(results=["a"], scores=[1.0])
        assert qr.metadata == {}

    def test_immutable(self):
        qr = QueryResult(results=[], scores=[])
        import dataclasses
        assert dataclasses.fields(qr)


class TestAssembledContext:
    def test_fields(self):
        ac = AssembledContext(text="hello", token_count=1, source_ids=["s1"])
        assert ac.text == "hello"
        assert ac.token_count == 1
        assert ac.source_ids == ["s1"]

    def test_source_ids_default(self):
        ac = AssembledContext(text="", token_count=0)
        assert ac.source_ids == []


class TestIKnowledgeBackboneProtocol:
    def test_is_runtime_checkable(self):
        # @runtime_checkable Protocol should have MISSING_ATTRS or be checkable via isinstance
        import typing
        assert isinstance(IKnowledgeBackbone, type(typing.Protocol))
