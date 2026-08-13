"""Compute eval metrics for one route: precision / recall / F1 /
hallucination_rate / op_accuracy.

Definitions (from plan):
  actual   — {entity: {field: op}} from production Sonnet output
  expected — {entity: {field: op}} from oracle fixture (ground truth)
  valid    — {entity: [field, ...]} known fields from route_context.entities

  true_positive  : field in both actual & expected, ops match
  false_positive : field in actual but NOT in expected
                   (but IS in valid_fields — over-detection, not hallucination)
  false_negative : field in expected but NOT in actual
  hallucinated   : field in actual but NOT in valid_fields at all
                   (more severe than false positive)
  name_matched   : field present in both (regardless of op)
  op_correct     : name_matched AND ops match

All comparisons are done after normalize_field() + normalize_op().
Entity names are compared case-insensitively.
"""
from __future__ import annotations

from .models import OracleFixture, RouteMetrics
from .normalizer import normalize_field, normalize_op


def compute_metrics(
    actual_cells: dict[str, dict[str, str]],
    fixture: OracleFixture,
) -> RouteMetrics:
    """Compare actual production output against oracle fixture ground truth.

    Args:
        actual_cells: {entity_short_name: {field_or_db_col: op_string}}
                      as returned by the production CRUD matrix phase.
        fixture:      OracleFixture loaded from disk.
    Returns:
        RouteMetrics with all computed values.
    """
    # Build normalized lookup tables
    # expected: entity_lower -> field_norm -> op_norm
    expected: dict[str, dict[str, str]] = {}
    for entity, fields in fixture.expected.items():
        ek = entity.lower()
        expected[ek] = {normalize_field(f): normalize_op(c.op) for f, c in fields.items()}

    # valid_fields: entity_lower -> set[field_norm]
    valid: dict[str, set[str]] = {}
    for entity, flist in fixture.valid_fields.items():
        valid[entity.lower()] = {normalize_field(f) for f in flist}

    # actual: entity_lower -> field_norm -> op_norm
    actual: dict[str, dict[str, str]] = {}
    for entity, fields in actual_cells.items():
        ek = entity.lower()
        actual[ek] = {normalize_field(f): normalize_op(op) for f, op in fields.items()}

    tp = fp = fn = hallucinated = name_matched = op_correct = 0

    # Walk actual output
    for entity, a_fields in actual.items():
        e_fields = expected.get(entity, {})
        v_fields = valid.get(entity, set())

        for field_norm, actual_op in a_fields.items():
            if field_norm not in v_fields and v_fields:
                # Field doesn't exist in the entity at all → hallucination
                hallucinated += 1
                fp += 1
                continue

            if field_norm in e_fields:
                name_matched += 1
                if actual_op == e_fields[field_norm]:
                    tp += 1
                    op_correct += 1
                else:
                    fp += 1  # wrong op
            else:
                # In valid_fields but oracle didn't include it → false positive (over-detect)
                fp += 1

    # Walk expected to find false negatives
    for entity, e_fields in expected.items():
        a_fields = actual.get(entity, {})
        for field_norm in e_fields:
            if field_norm not in a_fields:
                fn += 1

    total_actual = sum(len(f) for f in actual.values())
    total_expected = sum(len(f) for f in expected.values())

    precision = tp / total_actual if total_actual > 0 else 0.0
    recall = tp / total_expected if total_expected > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    hallucination_rate = hallucinated / total_actual if total_actual > 0 else 0.0
    op_acc = op_correct / name_matched if name_matched > 0 else 0.0

    return RouteMetrics(
        fixture_id=fixture.fixture_id,
        precision=precision,
        recall=recall,
        f1=f1,
        hallucination_rate=hallucination_rate,
        op_accuracy=op_acc,
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        hallucinated=hallucinated,
        name_matched=name_matched,
        op_correct=op_correct,
    )
