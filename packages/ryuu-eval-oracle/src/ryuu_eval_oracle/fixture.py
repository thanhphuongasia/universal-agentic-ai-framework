from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class OracleFixture:
    """Generic oracle ground truth fixture.

    ``expected`` is a project-defined JSON-serialisable dict — intentionally
    untyped here so any domain can extend without subclassing.
    """

    fixture_id: str
    prompt_version: str
    input_data: dict[str, Any]
    expected: dict[str, Any]
    oracle_model: str = "claude-opus-4-7"
    reviewed_by: str = ""
    reviewed_at: str = ""
    review_note: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "prompt_version": self.prompt_version,
            "input_data": self.input_data,
            "expected": self.expected,
            "oracle_model": self.oracle_model,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at,
            "review_note": self.review_note,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> OracleFixture:
        return cls(
            fixture_id=d["fixture_id"],
            prompt_version=d.get("prompt_version", ""),
            input_data=d.get("input_data", {}),
            expected=d.get("expected", {}),
            oracle_model=d.get("oracle_model", "claude-opus-4-7"),
            reviewed_by=d.get("reviewed_by", ""),
            reviewed_at=d.get("reviewed_at", ""),
            review_note=d.get("review_note", ""),
            meta=d.get("meta", {}),
        )
