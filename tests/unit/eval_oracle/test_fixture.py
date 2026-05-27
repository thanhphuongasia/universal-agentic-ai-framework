from ryuu_eval_oracle import OracleFixture


def _make() -> OracleFixture:
    return OracleFixture(
        fixture_id="case1",
        prompt_version="crud.oracle.v1",
        input_data={"route": "POST /orders"},
        expected={"cells": []},
        oracle_model="claude-opus-4-7",
        meta={"framework": "spring"},
    )


def test_to_dict_has_all_keys():
    d = _make().to_dict()
    assert set(d) == {
        "fixture_id", "prompt_version", "input_data", "expected",
        "oracle_model", "reviewed_by", "reviewed_at", "review_note", "meta",
    }


def test_from_dict_round_trip():
    original = _make()
    restored = OracleFixture.from_dict(original.to_dict())
    assert restored.fixture_id == original.fixture_id
    assert restored.prompt_version == original.prompt_version
    assert restored.input_data == original.input_data
    assert restored.expected == original.expected
    assert restored.meta == original.meta


def test_from_dict_defaults_for_missing_keys():
    restored = OracleFixture.from_dict({"fixture_id": "x"})
    assert restored.prompt_version == ""
    assert restored.input_data == {}
    assert restored.expected == {}
    assert restored.oracle_model == "claude-opus-4-7"
    assert restored.meta == {}
