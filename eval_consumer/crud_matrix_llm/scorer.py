"""Project-specific scorer for the crud_matrix_llm eval suite.

Designed to run AFTER CrudMatrixTarget has normalized both sides to the
flat ``{entity::column: op}`` shape. Compares dicts directly.

Score = matched_cells / union(expected_cells, actual_cells).
Empty expected + empty actual → 1.0 (correct empty matrix).
"""

from __future__ import annotations

import json
from typing import Any

from ryuu_eval_core.models import EvalCase, ScoreResult


class CRUDOpsMatch:
    scorer_id = "crud-ops-match"

    def __init__(self, threshold: float = 0.8) -> None:
        self._threshold = threshold

    async def score(self, case: EvalCase, output: str) -> ScoreResult:
        expected = _to_flat_ops(case.expected)
        actual = _to_flat_ops(output)

        all_keys = set(expected) | set(actual)
        if not all_keys:
            return ScoreResult(
                scorer_id=self.scorer_id, score=1.0, passed=True,
                reason="both empty — correct empty matrix",
            )

        matched = sum(1 for k in all_keys if expected.get(k) == actual.get(k))
        score = matched / len(all_keys)
        return ScoreResult(
            scorer_id=self.scorer_id,
            score=score,
            passed=score >= self._threshold,
            reason=f"{matched}/{len(all_keys)} ops match (threshold={self._threshold})",
        )


def _to_flat_ops(value: Any) -> dict[str, str]:
    """Coerce expected/actual into flat ``{entity::field: op}`` dict.

    Handles three shapes:
      1. Already flat: ``{"Order::status": "C"}`` — returned as-is
      2. Legacy expected: ``{"cells": [{entity, column, op}]}`` — flattened
      3. Legacy actual:   ``{"Order": {"status": {"op": "C", ...}}}`` — flattened
    """
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {}
    if not isinstance(value, dict):
        return {}

    # Shape 2: legacy expected with cells
    cells = value.get("cells")
    if isinstance(cells, list):
        flat: dict[str, str] = {}
        for c in cells:
            if isinstance(c, dict):
                e, col, op = c.get("entity", ""), c.get("column", ""), c.get("op", "")
                if e and col and op:
                    flat[f"{e}::{col}"] = op
        return flat

    # Shape 3: legacy actual with nested {Entity: {field: {op, ...}}}
    is_nested = any(
        isinstance(v, dict) and any(isinstance(sv, dict) and "op" in sv for sv in v.values())
        for v in value.values()
    )
    if is_nested:
        flat = {}
        for entity, fields in value.items():
            if isinstance(fields, dict):
                for field, cell in fields.items():
                    if isinstance(cell, dict) and cell.get("op"):
                        flat[f"{entity}::{field}"] = cell["op"]
        return flat

    # Shape 1: assume already flat — keep only string op values
    return {k: v for k, v in value.items() if isinstance(v, str)}
