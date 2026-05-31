"""Unit tests for eval_consumer.crud_matrix_llm.target.

Covers the robustness fixes:
  - _extract_json_obj / _parse_actual : tolerate prose-wrapped JSON, flag real failures
  - _flatten_expected                 : accept every oracle/fixture expected shape
  - _unwrap_leaked                    : strip leaked $FUNCTION_NAME wrapper, keep real single-entity
  - _detailed_cells                   : preserve confidence + why for the trace
  - CrudMatrixTarget.run              : surface parse failure vs valid empty matrix
"""
from __future__ import annotations

import json

from ryuu_eval_core.models import CaseResult, EvalCase

from eval_consumer.crud_matrix_llm.target import (
    CrudMatrixTarget,
    _detailed_cells,
    _extract_json_obj,
    _flatten_expected,
    _parse_actual,
    _unwrap_leaked,
)


# ---------------------------------------------------------------------------
# _extract_json_obj — robust JSON extraction
# ---------------------------------------------------------------------------

class TestExtractJsonObj:
    def test_bare_json(self):
        assert _extract_json_obj('{"a": 1}') == {"a": 1}

    def test_fenced_whole(self):
        assert _extract_json_obj('```json\n{"a": 1}\n```') == {"a": 1}

    def test_json_then_trailing_prose(self):
        # The claude-sonnet-4-6 failure shape: valid JSON + markdown table after.
        raw = '```json\n{"Order": {"total": {"op": "C"}}}\n```\n\n**Walkthrough:** blah {x}'
        assert _extract_json_obj(raw) == {"Order": {"total": {"op": "C"}}}

    def test_prose_before_json(self):
        assert _extract_json_obj('Here you go:\n{"a": 1}') == {"a": 1}

    def test_no_json_returns_none(self):
        assert _extract_json_obj("I cannot answer that.") is None

    def test_malformed_first_then_valid(self):
        # First "{" opens a broken object; scanner moves to the next candidate.
        assert _extract_json_obj('{bad} then {"a": 1}') == {"a": 1}


# ---------------------------------------------------------------------------
# _parse_actual — distinguish "valid empty" from "parse failed"
# ---------------------------------------------------------------------------

class TestParseActual:
    def test_empty_matrix_is_valid_not_failure(self):
        parsed, flat = _parse_actual("{}")
        assert parsed == {} and flat == {}  # parsed is {} (not None) → NOT a failure

    def test_prose_only_is_failure(self):
        parsed, flat = _parse_actual("no json here")
        assert parsed is None and flat == {}

    def test_dict_passthrough(self):
        parsed, flat = _parse_actual({"Order": {"total": {"op": "C"}}})
        assert parsed is not None and flat == {"Order::total": "C"}


# ---------------------------------------------------------------------------
# _flatten_expected — accept every oracle/fixture shape
# ---------------------------------------------------------------------------

class TestFlattenExpected:
    def test_list_shape(self):
        exp = {"cells": [{"entity": "Order", "column": "total", "op": "C"}]}
        assert _flatten_expected(exp) == {"Order::total": "C"}

    def test_cells_dict_shape(self):
        exp = {"cells": {"User": {"id": {"op": "R"}, "email": {"op": "R"}}}}
        assert _flatten_expected(exp) == {"User::id": "R", "User::email": "R"}

    def test_bare_nested_shape(self):
        exp = {"Order": {"status": {"op": "C", "confidence": "high"}}}
        assert _flatten_expected(exp) == {"Order::status": "C"}

    def test_leaked_function_name_wrapper(self):
        exp = {"cells": {"$FUNCTION_NAME": {"Order": {"id": {"op": "R"}}}}}
        assert _flatten_expected(exp) == {"Order::id": "R"}

    def test_drops_empty_op(self):
        exp = {"Order": {"id": {"op": ""}, "total": {"op": "C"}}}
        assert _flatten_expected(exp) == {"Order::total": "C"}

    def test_json_string_input(self):
        assert _flatten_expected('{"cells": [{"entity": "O", "column": "c", "op": "R"}]}') == {"O::c": "R"}

    def test_garbage_returns_empty(self):
        assert _flatten_expected("not json") == {}
        assert _flatten_expected(123) == {}


# ---------------------------------------------------------------------------
# _unwrap_leaked — only unwrap a genuine wrapper
# ---------------------------------------------------------------------------

class TestUnwrapLeaked:
    def test_unwraps_wrapper(self):
        node = {"$FUNCTION_NAME": {"Order": {"status": {"op": "C"}}}}
        assert _unwrap_leaked(node) == {"Order": {"status": {"op": "C"}}}

    def test_keeps_genuine_single_entity(self):
        # {Order: {status: {op}}} is a real one-entity matrix — must NOT unwrap.
        node = {"Order": {"status": {"op": "C"}}}
        assert _unwrap_leaked(node) == node


# ---------------------------------------------------------------------------
# _detailed_cells — preserve confidence + why for the trace
# ---------------------------------------------------------------------------

class TestDetailedCells:
    def test_preserves_confidence_and_reason(self):
        parsed = {"Order": {"total": {"op": "C", "confidence": 0.9, "reason": "POST write"}}}
        rows = _detailed_cells(parsed)
        assert rows == [{"entity": "Order", "field": "total", "op": "C",
                         "confidence": 0.9, "why": "POST write"}]

    def test_why_falls_back_across_keys(self):
        parsed = {"E": {"f": {"op": "R", "oracle_why": "ground truth note"}}}
        assert _detailed_cells(parsed)[0]["why"] == "ground truth note"

    def test_none_returns_empty(self):
        assert _detailed_cells(None) == []

    def test_unwraps_leaked_wrapper(self):
        parsed = {"$FN": {"Order": {"total": {"op": "C"}}}}
        rows = _detailed_cells(parsed)
        assert rows and rows[0]["entity"] == "Order"


# ---------------------------------------------------------------------------
# CrudMatrixTarget.run — error surfacing + normalization
# ---------------------------------------------------------------------------

class _FakeBase:
    def __init__(self, output: str, error: str | None = None) -> None:
        self._output = output
        self._error = error

    async def run(self, case: EvalCase) -> CaseResult:
        return CaseResult(case=case, output=self._output, steps=[], error=self._error)


def _case(expected) -> EvalCase:
    return EvalCase(case_id="c", input={}, expected=expected)


async def test_run_prose_wrapped_json_is_parsed_no_error():
    raw = '```json\n{"Order": {"total": {"op": "C"}}}\n```\n\n**Walkthrough:** ...'
    cr = await CrudMatrixTarget(_FakeBase(raw)).run(
        _case({"cells": [{"entity": "Order", "column": "total", "op": "C"}]})
    )
    assert cr.error is None
    assert json.loads(cr.output) == {"Order::total": "C"}


async def test_run_prose_only_surfaces_parse_error():
    cr = await CrudMatrixTarget(_FakeBase("I cannot produce that.")).run(_case({"cells": []}))
    assert cr.error is not None and "crud-parse" in cr.error
    assert cr.output == "{}"


async def test_run_empty_matrix_is_not_an_error():
    cr = await CrudMatrixTarget(_FakeBase("{}")).run(_case({"cells": []}))
    assert cr.error is None
    assert cr.output == "{}"


async def test_run_emits_detailed_trace_step():
    raw = '{"Order": {"total": {"op": "C", "confidence": 0.9, "reason": "why"}}}'
    cr = await CrudMatrixTarget(_FakeBase(raw)).run(
        _case({"cells": [{"entity": "Order", "column": "total", "op": "C"}]})
    )
    labels = [s.get("label", "") for s in cr.steps]
    assert any("rationale" in lbl for lbl in labels)
