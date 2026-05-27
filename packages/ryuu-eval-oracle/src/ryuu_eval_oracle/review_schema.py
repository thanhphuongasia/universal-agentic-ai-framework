from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ReviewKind = Literal["table", "graph", "tree", "timeline"]


@dataclass
class ReviewSchema:
    """Describes how the Oracle Review UI should render candidates for a domain.

    UI reads this schema to decide which renderer to mount.  Strategy returns
    a ReviewSchema from ``review_schema()``; the HTTP layer serialises it and
    serves it to the frontend.

    Fields per kind:
      - ``table``    → populate ``columns``
      - ``graph``    → populate ``node_fields`` + ``edge_fields``
      - ``tree``     → populate ``node_fields``
      - ``timeline`` → populate ``columns``
    """

    kind: ReviewKind
    columns: list[str] = field(default_factory=list)
    node_fields: list[str] = field(default_factory=list)
    edge_fields: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=lambda: ["approve", "fix", "remove"])
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "columns": self.columns,
            "node_fields": self.node_fields,
            "edge_fields": self.edge_fields,
            "actions": self.actions,
            "meta": self.meta,
        }
