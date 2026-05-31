"""Project-specific target wrapper for the crud_matrix_llm suite.

Normalizes BOTH case.expected and LLM output to the same flat shape
``{entity::column: op}`` before they reach the generic UI. This way the
framework UI shows a clean diff without knowing anything about CRUD —
all project-specific logic stays in this package.

Also emits extra trace steps (parsed ops, comparison summary) so the
trace panel reflects the full LLM-to-evaluation pipeline.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from ryuu_eval_core.models import CaseResult, EvalCase


class CrudMatrixTarget:
    """Wraps a base EvalTarget. Both expected + actual become flat op maps."""

    def __init__(self, base: Any) -> None:
        self._base = base

    async def run(self, case: EvalCase) -> CaseResult:
        # 1. Normalize case.expected before the base target sees it.
        normalized_expected = _flatten_expected(case.expected)
        case_norm = replace(case, expected=normalized_expected)

        # 2. Run the LLM via the wrapped base target.
        result = await self._base.run(case_norm)

        # 3. Normalize the LLM output. ``parsed`` is None when no JSON object
        #    could be extracted at all (vs. a valid but empty ``{}`` matrix).
        raw_output = result.output
        parsed, normalized_actual = _parse_actual(raw_output)
        parse_failed = parsed is None and bool(str(raw_output).strip())

        # 4. Augment trace with project-specific derived steps so the
        #    user can see the normalization pipeline.
        steps = list(result.steps)
        steps.append({
            "type": "llm_output",
            "content": json.dumps(normalized_actual, indent=2, ensure_ascii=False),
            "label": "parsed CRUD ops (normalized)",
        })

        # Per-cell breakdown WITH the model's self-rating (confidence + why).
        # Scoring strips these as noise, but they're the most useful signal for
        # a human inspecting *why* the model picked an op — so keep them in the
        # trace, split into entity / field / op / confidence / why columns.
        detailed = _detailed_cells(parsed)
        if detailed:
            steps.append({
                "type": "observation",
                "content": json.dumps(detailed, indent=2, ensure_ascii=False),
                "label": f"CRUD cells w/ rationale ({len(detailed)})",
            })

        # Comparison summary step
        all_keys = set(normalized_expected) | set(normalized_actual)
        matched = sum(
            1 for k in all_keys
            if normalized_expected.get(k) == normalized_actual.get(k)
        )
        missing = [k for k in normalized_expected if k not in normalized_actual]
        extra = [k for k in normalized_actual if k not in normalized_expected]
        mismatched = [
            f"{k}: expected={normalized_expected.get(k)!r} actual={normalized_actual.get(k)!r}"
            for k in all_keys
            if k in normalized_expected and k in normalized_actual
            and normalized_expected[k] != normalized_actual[k]
        ]
        summary = {
            "matched": matched,
            "total": len(all_keys),
            "missing_in_actual": missing,
            "extra_in_actual": extra,
            "mismatched_op": mismatched,
        }
        steps.append({
            "type": "observation",
            "content": json.dumps(summary, indent=2, ensure_ascii=False),
            "label": f"comparison: {matched}/{len(all_keys)} ops match"
                     if all_keys else "comparison: empty matrix",
        })

        # 5. Surface a parse failure instead of silently scoring an empty
        #    matrix as 0. A model that emits valid JSON wrapped in prose used
        #    to fall through to ``{}`` with no error — making a correct answer
        #    look like a wrong one. Now it's an explicit, visible failure.
        new_error = result.error
        if parse_failed:
            note = "crud-parse: no JSON object found in model output (see raw trace step)"
            new_error = f"{result.error}; {note}" if result.error else note

        # 6. Return CaseResult with normalized expected + normalized output.
        #    Raw LLM JSON is preserved in steps for inspection.
        return replace(
            result,
            case=case_norm,
            output=json.dumps(normalized_actual, ensure_ascii=False),
            steps=steps,
            error=new_error,
        )


# ---------------------------------------------------------------------------
# Normalizers
# ---------------------------------------------------------------------------

def _has_op_cells(d: Any) -> bool:
    """True if ``d`` is a ``{field: {op: ...}}`` map (its values are op-cells)."""
    return isinstance(d, dict) and any(
        isinstance(v, dict) and "op" in v for v in d.values()
    )


def _unwrap_leaked(node: dict) -> dict:
    """Drop a single leaked wrapper key (e.g. ``$FUNCTION_NAME``) the oracle LLM
    sometimes emits around the entity map: ``{"$FN": {Entity: {field: cell}}}``.

    Only unwraps when the sole value is itself a nested entity map — never a
    legitimate single-entity result like ``{Order: {status: {op}}}``.
    """
    if len(node) == 1:
        (_, v), = node.items()
        if isinstance(v, dict) and any(_has_op_cells(sub) for sub in v.values()):
            return v
    return node


def _flatten_expected(expected: Any) -> dict[str, str]:
    """Normalize any oracle/fixture ``expected`` shape → ``{entity::column: op}``.

    Tolerates every shape the oracle pipeline has emitted across prompt versions:
      1. ``{cells: [{entity, column, op}, ...]}``      — promoted eval-case YAML
      2. ``{cells: {entity: {field: {op, ...}}}}``     — reviewed oracle fixture
      3. ``{entity: {field: {op, ...}}}``              — bare nested (older fixture)
      4. any of the above under a leaked ``$FUNCTION_NAME`` wrapper key
    Cells with empty ``op`` (omitted) are dropped.
    """
    if isinstance(expected, str):
        try:
            expected = json.loads(expected)
        except json.JSONDecodeError:
            return {}
    if not isinstance(expected, dict):
        return {}

    cells = expected.get("cells")

    # Shape 1: cells is a flat list of {entity, column, op}.
    if isinstance(cells, list):
        flat: dict[str, str] = {}
        for cell in cells:
            if not isinstance(cell, dict):
                continue
            e, c, op = cell.get("entity", ""), cell.get("column", ""), cell.get("op", "")
            if e and c and op:
                flat[f"{e}::{c}"] = op
        return flat

    # Shapes 2-4: a nested {entity: {field: {op}}} map, optionally under a
    # "cells" dict and/or a leaked wrapper key.
    node = cells if isinstance(cells, dict) else expected
    return _flatten_obj(_unwrap_leaked(node))


def _extract_json_obj(text: str) -> dict | None:
    """Find and parse the first balanced top-level ``{...}`` object in ``text``.

    Robust to the common LLM output shapes that a naive ``json.loads`` chokes on:
      - bare JSON                       → parsed
      - ```json fenced``` whole reply   → parsed (markers sit outside the braces)
      - JSON followed by prose / a table → parsed (we stop at the matching brace)
      - prose followed by JSON          → parsed (we scan forward to the first ``{``)

    Returns ``None`` only when no parseable object exists at all.
    """
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break  # malformed — try the next ``{``
        start = text.find("{", start + 1)
    return None


def _parse_actual(output: Any) -> tuple[dict | None, dict[str, str]]:
    """Return ``(parsed_obj_or_None, flat_ops)``.

    ``parsed_obj`` is ``None`` when no JSON object could be extracted — the
    caller uses that to distinguish a real parse failure from a legitimately
    empty ``{}`` matrix.
    """
    if isinstance(output, str):
        obj = _extract_json_obj(output)
    elif isinstance(output, dict):
        obj = output
    else:
        obj = None
    if obj is None:
        return None, {}
    return obj, _flatten_obj(obj)


def _flatten_obj(output: dict) -> dict[str, str]:
    """``{Entity: {field: {op, confidence, reason}}}`` → ``{entity::field: op}``.

    Strips ``confidence`` and ``reason`` — LLM self-rating noise, not part of
    the ground truth comparison.
    """
    flat: dict[str, str] = {}
    for entity, fields in output.items():
        if not isinstance(fields, dict):
            continue
        for field, cell in fields.items():
            if isinstance(cell, dict) and cell.get("op"):
                flat[f"{entity}::{field}"] = cell["op"]
    return flat


def _detailed_cells(parsed: dict | None) -> list[dict[str, Any]]:
    """``{Entity: {field: {op, confidence, reason}}}`` → a flat row list with
    entity / field / op split out and the model's confidence + why preserved.

    For trace/inspection only — never feeds scoring. Tolerates the wrapper and
    nested shapes via the same unwrap the expected side uses.
    """
    if not isinstance(parsed, dict):
        return []
    obj = _unwrap_leaked(parsed)
    rows: list[dict[str, Any]] = []
    for entity, fields in obj.items():
        if not isinstance(fields, dict):
            continue
        for field, cell in fields.items():
            if not isinstance(cell, dict) or not cell.get("op"):
                continue
            rows.append({
                "entity": entity,
                "field": field,
                "op": cell.get("op"),
                "confidence": cell.get("confidence"),
                "why": cell.get("reason") or cell.get("why") or cell.get("oracle_why"),
            })
    return rows
