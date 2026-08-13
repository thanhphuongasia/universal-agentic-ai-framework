"""Normalize op strings and field names before comparison.

Two problems this solves (gaps 1 & 2 from plan review):
  Gap 1 — op ordering: Opus/Sonnet may output "RC" instead of "CR".
           Normalize to CRUD order before any comparison.
  Gap 2 — field name casing: production may output camelCase ("customerId")
           while fixture stores snake_case or db_column ("customer_id").
           Normalize both sides to lowercase-no-separator before matching.
"""
from __future__ import annotations

_OP_ORDER = {"C": 0, "R": 1, "U": 2, "D": 3}


def normalize_op(op: str) -> str:
    """Sort op chars into CRUD order and deduplicate.

    Examples:
        "RC"  -> "CR"
        "URC" -> "CRU"
        "c"   -> "C"
        ""    -> ""
    """
    chars = set(op.upper()) & _OP_ORDER.keys()
    return "".join(sorted(chars, key=lambda c: _OP_ORDER[c]))


def normalize_field(name: str) -> str:
    """Collapse camelCase / snake_case / PascalCase to lowercase token.

    Examples:
        "customerId"  -> "customerid"
        "customer_id" -> "customerid"
        "CustomerID"  -> "customerid"
    """
    return name.replace("_", "").replace("-", "").lower()


def normalize_flat_ops(flat: dict[str, str]) -> dict[str, str]:
    """Normalize a flat ``{entity::field: op}`` map for comparison.

    Entity is lowercased, field run through :func:`normalize_field`, op through
    :func:`normalize_op`. This is what makes a production answer keyed
    ``Order::customerId`` match a fixture keyed ``order::customer_id`` — the
    casing/separator differences collapse to one canonical key before the
    scorer counts matches.

    Keys without the ``::`` separator are normalized whole (defensive).

    Examples::

        {"Order::customerId": "RC"}  -> {"order::customerid": "CR"}
        {"User::email": "r"}         -> {"user::email": "R"}
    """
    result: dict[str, str] = {}
    for key, op in flat.items():
        if "::" in key:
            entity, _, field = key.partition("::")
            norm_key = f"{entity.lower()}::{normalize_field(field)}"
        else:
            norm_key = normalize_field(key)
        result[norm_key] = normalize_op(op)
    return result


def normalize_cells(
    cells: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    """Normalize a full {entity: {field: op}} dict in-place → new dict.

    Returns a new dict where:
      - entity keys are lowercased
      - field keys are normalize_field()-ed
      - op values are normalize_op()-ed
    """
    result: dict[str, dict[str, str]] = {}
    for entity, fields in cells.items():
        norm_entity = entity.lower()
        result[norm_entity] = {
            normalize_field(f): normalize_op(op)
            for f, op in fields.items()
        }
    return result
