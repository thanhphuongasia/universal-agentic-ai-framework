"""CRUD Matrix oracle eval — project-specific models.

CRUDFixture extends the generic OracleFixture with CRUD cell typing and
a valid_fields hallucination check vocabulary.
RouteMetrics + EvalReport hold per-route and aggregate eval results.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from ryuu_eval_core.oracle import OracleFixture

Confidence = Literal["low", "medium", "high"]


@dataclass
class CRUDCell:
    """One (entity, field) oracle cell."""
    op: str                    # normalized CRUD string, e.g. "C", "CR", "RU"
    confidence: Confidence = "high"
    oracle_why: str = ""


@dataclass
class CRUDFixture:
    """CRUD Matrix oracle fixture — wraps OracleFixture with typed cells."""
    base: OracleFixture
    # cells[entity][field] = CRUDCell
    cells: dict[str, dict[str, CRUDCell]] = field(default_factory=dict)
    # valid_fields[entity] = known db_column / field names from route_context
    valid_fields: dict[str, list[str]] = field(default_factory=dict)

    @property
    def fixture_id(self) -> str:
        return self.base.fixture_id

    def to_dict(self) -> dict[str, Any]:
        d = self.base.to_dict()
        d["expected"] = {
            entity: {
                fname: {"op": c.op, "confidence": c.confidence, "oracle_why": c.oracle_why}
                for fname, c in fmap.items()
            }
            for entity, fmap in self.cells.items()
        }
        d["meta"]["valid_fields"] = self.valid_fields
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CRUDFixture:
        base = OracleFixture.from_dict(d)
        cells: dict[str, dict[str, CRUDCell]] = {}
        for entity, fmap in (d.get("expected") or {}).items():
            cells[entity] = {
                f: CRUDCell(
                    op=c["op"],
                    confidence=c.get("confidence", "high"),
                    oracle_why=c.get("oracle_why", ""),
                )
                for f, c in fmap.items()
            }
        valid_fields = d.get("meta", {}).get("valid_fields", {})
        return cls(base=base, cells=cells, valid_fields=valid_fields)

    def review_items(self) -> list[dict[str, Any]]:
        """Return cells with low/medium confidence for human review."""
        items = []
        for entity, fmap in self.cells.items():
            for fname, cell in fmap.items():
                if cell.confidence in ("low", "medium"):
                    items.append({
                        "entity": entity,
                        "field": fname,
                        "op": cell.op,
                        "confidence": cell.confidence,
                        "oracle_why": cell.oracle_why,
                        "action": None,       # reviewer fills: approve | fix | remove
                        "corrected_op": None,
                    })
        return items


@dataclass
class RouteMetrics:
    """Eval metrics for one route."""
    fixture_id: str
    precision: float
    recall: float
    f1: float
    hallucination_rate: float
    op_accuracy: float
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    hallucinated: int = 0
    name_matched: int = 0
    op_correct: int = 0


@dataclass
class EvalReport:
    """Full report across all fixtures in one eval run."""
    routes: list[RouteMetrics] = field(default_factory=list)
    prompt_version: str = ""

    @property
    def avg_precision(self) -> float:
        return _avg(r.precision for r in self.routes)

    @property
    def avg_recall(self) -> float:
        return _avg(r.recall for r in self.routes)

    @property
    def avg_f1(self) -> float:
        return _avg(r.f1 for r in self.routes)

    @property
    def avg_hallucination_rate(self) -> float:
        return _avg(r.hallucination_rate for r in self.routes)

    @property
    def avg_op_accuracy(self) -> float:
        return _avg(r.op_accuracy for r in self.routes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt_version": self.prompt_version,
            "summary": {
                "precision": round(self.avg_precision, 4),
                "recall": round(self.avg_recall, 4),
                "f1": round(self.avg_f1, 4),
                "hallucination_rate": round(self.avg_hallucination_rate, 4),
                "op_accuracy": round(self.avg_op_accuracy, 4),
                "route_count": len(self.routes),
            },
            "routes": [
                {
                    "fixture_id": r.fixture_id,
                    "precision": round(r.precision, 4),
                    "recall": round(r.recall, 4),
                    "f1": round(r.f1, 4),
                    "hallucination_rate": round(r.hallucination_rate, 4),
                    "op_accuracy": round(r.op_accuracy, 4),
                    "tp": r.true_positives,
                    "fp": r.false_positives,
                    "fn": r.false_negatives,
                    "hallucinated": r.hallucinated,
                }
                for r in self.routes
            ],
        }


def _avg(values) -> float:
    lst = list(values)
    return sum(lst) / len(lst) if lst else 0.0
