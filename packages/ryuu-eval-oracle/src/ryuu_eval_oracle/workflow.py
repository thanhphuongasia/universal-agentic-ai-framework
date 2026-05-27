from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ryuu_eval_oracle.fixture import OracleFixture


class OracleWorkflow:
    """Orchestrate: fetch input → (optional) run production → generate candidate → persist.

    Accepts any objects that satisfy IInputSource, IOracleStrategy, and
    IProductionTarget — duck-typed to avoid import overhead for callers
    that only use a subset of the protocols.
    """

    def __init__(
        self,
        strategy: Any,
        input_source: Any,
        *,
        production_target: Any | None = None,
        prompt_version: str = "unknown",
        out_dir: str | Path = Path("artifacts/oracle"),
    ) -> None:
        self._strategy = strategy
        self._input_source = input_source
        self._production_target = production_target
        self._prompt_version = prompt_version
        self._out_dir = Path(out_dir)

    async def run_case(self, case_id: str) -> OracleFixture:
        """Full pipeline for one case. Returns the persisted fixture."""
        input_data = await self._input_source.fetch(case_id)
        existing: Any | None = None
        if self._production_target is not None:
            existing = await self._production_target.run(input_data)
        candidate = await self._strategy.generate_candidate(input_data, existing_output=existing)
        input_dict = input_data if isinstance(input_data, dict) else {"raw": input_data}
        expected_dict = candidate if isinstance(candidate, dict) else {"raw": candidate}
        fixture = OracleFixture(
            fixture_id=case_id,
            prompt_version=self._prompt_version,
            input_data=input_dict,
            expected=expected_dict,
        )
        self.save_fixture(fixture)
        return fixture

    def save_fixture(self, fixture: OracleFixture, out_dir: Path | None = None) -> Path:
        """Write fixture as <fixture_id>.json. Returns written path."""
        target = out_dir or self._out_dir
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"{fixture.fixture_id}.json"
        path.write_text(
            json.dumps(fixture.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def save_review(
        self,
        items: list[dict[str, Any]],
        fixture_id: str,
        *,
        out_dir: Path | None = None,
        generated_at: str = "",
    ) -> Path | None:
        """Write <fixture_id>.review.json for items needing human review.

        Returns None (and writes nothing) when items is empty.
        Items structure is project-defined.
        """
        if not items:
            return None
        target = out_dir or self._out_dir
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"{fixture_id}.review.json"
        path.write_text(
            json.dumps(
                {
                    "fixture_id": fixture_id,
                    "generated_at": generated_at,
                    "needs_review": items,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return path
