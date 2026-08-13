"""CRUD-specific normalization for op strings and field names.

Used by both generate.py (oracle side) and runner.py (comparison side)
so both sides normalize identically before any comparison.
"""
from __future__ import annotations

_OP_ORDER = {"C": 0, "R": 1, "U": 2, "D": 3}


def normalize_op(op: str) -> str:
    """Sort op chars into CRUD order and deduplicate.

    "RC" → "CR", "URC" → "CRU", "" → ""
    """
    chars = set(op.upper()) & _OP_ORDER.keys()
    return "".join(sorted(chars, key=lambda c: _OP_ORDER[c]))


def normalize_field(name: str) -> str:
    """Collapse camelCase / snake_case / PascalCase to lowercase token.

    "customerId" → "customerid", "customer_id" → "customerid"
    """
    return name.replace("_", "").replace("-", "").lower()
