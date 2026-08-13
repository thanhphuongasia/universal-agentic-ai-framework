"""Data models for CRUD Matrix Oracle eval system."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


Confidence = Literal["low", "medium", "high"]


@dataclass
class OracleCell:
    """One (entity, field) cell produced by the oracle or production target."""
    op: str           # normalized: chars from {C,R,U,D} in CRUD order, e.g. "C", "CR", "RU"
    confidence: Confidence = "high"
    oracle_why: str = ""   # oracle chain-of-thought reasoning (empty for production output)


@dataclass
class OracleFixture:
    """Persisted oracle ground truth for one route."""
    fixture_id: str
    framework: str               # e.g. "java_spring"
    prompt_version: str          # e.g. "crud_matrix_oracle.v1" — for stale detection
    route_context: dict[str, Any]
    # expected[entity][field] = OracleCell
    expected: dict[str, dict[str, OracleCell]] = field(default_factory=dict)
    # valid_fields[entity] = list of known field names (from route_context.entities)
    valid_fields: dict[str, list[str]] = field(default_factory=dict)
    oracle_model: str = "claude-opus-4-7"
    reviewed_by: str = ""
    reviewed_at: str = ""
    review_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "framework": self.framework,
            "prompt_version": self.prompt_version,
            "route_context": self.route_context,
            "expected": {
                entity: {
                    field_name: {
                        "op": cell.op,
                        "confidence": cell.confidence,
                        "oracle_why": cell.oracle_why,
                    }
                    for field_name, cell in fields.items()
                }
                for entity, fields in self.expected.items()
            },
            "valid_fields": self.valid_fields,
            "oracle_model": self.oracle_model,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at,
            "review_note": self.review_note,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> OracleFixture:
        expected: dict[str, dict[str, OracleCell]] = {}
        for entity, fields in (d.get("expected") or {}).items():
            expected[entity] = {
                f: OracleCell(
                    op=c["op"],
                    confidence=c.get("confidence", "high"),
                    oracle_why=c.get("oracle_why", ""),
                )
                for f, c in fields.items()
            }
        return cls(
            fixture_id=d["fixture_id"],
            framework=d.get("framework", "java_spring"),
            prompt_version=d.get("prompt_version", ""),
            route_context=d.get("route_context", {}),
            expected=expected,
            valid_fields=d.get("valid_fields", {}),
            oracle_model=d.get("oracle_model", "claude-opus-4-7"),
            reviewed_by=d.get("reviewed_by", ""),
            reviewed_at=d.get("reviewed_at", ""),
            review_note=d.get("review_note", ""),
        )


@dataclass
class RouteMetrics:
    """Eval metrics for one route (one fixture)."""
    fixture_id: str
    precision: float       # correct / total_actual
    recall: float          # correct / total_expected
    f1: float              # 2*P*R/(P+R), 0.0 if both 0
    hallucination_rate: float   # fields NOT in valid_fields / total_actual
    op_accuracy: float     # name-matched cells with correct op / name-matched cells

    # raw counts for debugging
    true_positives: int = 0       # field+op both correct
    false_positives: int = 0      # field in actual but not expected (or wrong op counted separately)
    false_negatives: int = 0      # field in expected but not actual
    hallucinated: int = 0         # field not in valid_fields at all
    name_matched: int = 0         # fields where name matched (for op_accuracy denominator)
    op_correct: int = 0           # name-matched AND op correct


@dataclass
class EvalReport:
    """Full report for a run across all fixtures."""
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
                    "true_positives": r.true_positives,
                    "false_positives": r.false_positives,
                    "false_negatives": r.false_negatives,
                    "hallucinated": r.hallucinated,
                    "name_matched": r.name_matched,
                    "op_correct": r.op_correct,
                }
                for r in self.routes
            ],
        }


def _avg(values) -> float:
    lst = list(values)
    return sum(lst) / len(lst) if lst else 0.0
