import pytest
from ryuu_eval_oracle import ReviewSchema


def test_table_schema_defaults():
    s = ReviewSchema(kind="table", columns=["ENTITY", "FIELD", "OP"])
    assert s.kind == "table"
    assert s.columns == ["ENTITY", "FIELD", "OP"]
    assert s.actions == ["approve", "fix", "remove"]
    assert s.node_fields == []
    assert s.edge_fields == []


def test_graph_schema():
    s = ReviewSchema(
        kind="graph",
        node_fields=["class_name", "stereotype"],
        edge_fields=["from", "to", "kind"],
    )
    assert s.kind == "graph"
    assert s.node_fields == ["class_name", "stereotype"]
    assert s.edge_fields == ["from", "to", "kind"]


def test_to_dict_round_trip():
    s = ReviewSchema(
        kind="table",
        columns=["A", "B"],
        actions=["approve", "remove"],
        meta={"domain": "crud"},
    )
    d = s.to_dict()
    assert d["kind"] == "table"
    assert d["columns"] == ["A", "B"]
    assert d["actions"] == ["approve", "remove"]
    assert d["meta"] == {"domain": "crud"}


@pytest.mark.parametrize("kind", ["table", "graph", "tree", "timeline"])
def test_all_kinds_accepted(kind):
    s = ReviewSchema(kind=kind)  # type: ignore[arg-type]
    assert s.kind == kind
