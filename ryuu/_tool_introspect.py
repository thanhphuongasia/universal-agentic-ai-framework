"""Generate OpenAI function-calling schema from a Python callable.

Extracts:
    - name: fn.__name__
    - description: first line of docstring (empty string if no docstring)
    - parameters: from type hints (str → string, int → integer, etc.)
    - required: params without default values

Supported types (Phase 10 MVP):
    str / int / float / bool / list / dict

Complex types (Optional[T], list[T], TypedDict, Union) deferred to Phase 10.x.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, get_type_hints

_PY_TO_JSON: dict[type, dict[str, str]] = {
    str: {"type": "string"},
    int: {"type": "integer"},
    float: {"type": "number"},
    bool: {"type": "boolean"},
    list: {"type": "array"},
    dict: {"type": "object"},
}


def build_tool_schema(fn: Callable[..., Any]) -> dict[str, Any]:
    """Generate OpenAI function-calling schema from callable.

    Returns dict in OpenAI tool format::

        {
            "type": "function",
            "function": {
                "name": "<fn name>",
                "description": "<first line of docstring>",
                "parameters": {
                    "type": "object",
                    "properties": {...},
                    "required": [...],
                },
            },
        }
    """
    sig = inspect.signature(fn)
    hints = get_type_hints(fn)

    properties: dict[str, dict[str, str]] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue

        hint = hints.get(name, str)
        properties[name] = _type_to_json_schema(hint)

        if param.default is inspect.Parameter.empty:
            required.append(name)

    description = ""
    if fn.__doc__:
        description = fn.__doc__.strip().split("\n", 1)[0].strip()

    return {
        "type": "function",
        "function": {
            "name": fn.__name__,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


def _type_to_json_schema(py_type: Any) -> dict[str, str]:
    """Map Python type → JSON Schema fragment. Default to string for unknown."""
    # Handle generic types (list[str], dict[str, int]) by extracting origin
    origin = getattr(py_type, "__origin__", None)
    base = origin if origin is not None else py_type
    return _PY_TO_JSON.get(base, {"type": "string"})
