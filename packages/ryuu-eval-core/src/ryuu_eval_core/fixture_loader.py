from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ryuu_eval_core.models import EvalCase


class FixtureLoader:
    @staticmethod
    def load(path: str | Path) -> list[EvalCase]:
        data = json.loads(Path(path).read_text())
        cases_data: list[dict[str, Any]] = data if isinstance(data, list) else data.get("cases", [data])
        return FixtureLoader.load_json(cases_data)

    @staticmethod
    def load_json(data: list[dict[str, Any]]) -> list[EvalCase]:
        return [
            EvalCase(
                case_id=c.get("case_id", str(i)),
                input=c["input"],
                expected=c.get("expected"),
                metadata=c.get("metadata", {}),
            )
            for i, c in enumerate(data)
        ]
