"""OracleWorkflow orchestration tests — stub strategy + stub input source."""
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from ryuu_eval_oracle import OracleFixture, OracleWorkflow, ReviewSchema


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

def _make_input_source(_case_id: str, data: dict[str, Any]) -> Any:
    src = MagicMock()
    src.fetch = AsyncMock(return_value=data)
    return src


def _make_strategy(candidate: dict[str, Any]) -> Any:
    strat = MagicMock()
    strat.review_schema.return_value = ReviewSchema(kind="table", columns=["ENTITY", "FIELD"])
    strat.generate_candidate = AsyncMock(return_value=candidate)
    return strat


def _make_production_target(output: dict[str, Any]) -> Any:
    target = MagicMock()
    target.run = AsyncMock(return_value=output)
    return target


# ---------------------------------------------------------------------------
# Case B — no production target
# ---------------------------------------------------------------------------

async def test_case_b_calls_strategy_with_none_existing(tmp_path: Path) -> None:
    input_data = {"route": "POST /orders"}
    candidate = {"cells": [{"entity": "Order", "field": "status", "op": "C"}]}

    strategy = _make_strategy(candidate)
    workflow = OracleWorkflow(
        strategy=strategy,
        input_source=_make_input_source("case1", input_data),
        out_dir=tmp_path,
    )

    fixture = await workflow.run_case("case1")

    strategy.generate_candidate.assert_awaited_once_with(input_data, existing_output=None)
    assert isinstance(fixture, OracleFixture)
    assert fixture.fixture_id == "case1"
    assert fixture.expected == candidate


async def test_case_b_persists_fixture_to_disk(tmp_path: Path) -> None:
    strategy = _make_strategy({"cells": []})
    workflow = OracleWorkflow(
        strategy=strategy,
        input_source=_make_input_source("case1", {}),
        out_dir=tmp_path,
    )

    await workflow.run_case("case1")

    saved = json.loads((tmp_path / "case1.json").read_text())
    assert saved["fixture_id"] == "case1"


# ---------------------------------------------------------------------------
# Case A — with production target
# ---------------------------------------------------------------------------

async def test_case_a_passes_prod_output_to_strategy(tmp_path: Path) -> None:
    input_data = {"route": "GET /users"}
    prod_output = {"cells": [{"entity": "User", "field": "id", "op": "R"}]}
    candidate = {"cells": [{"entity": "User", "field": "id", "op": "R", "confidence": "high"}]}

    production_target = _make_production_target(prod_output)
    strategy = _make_strategy(candidate)
    workflow = OracleWorkflow(
        strategy=strategy,
        input_source=_make_input_source("case2", input_data),
        production_target=production_target,
        out_dir=tmp_path,
    )

    await workflow.run_case("case2")

    production_target.run.assert_awaited_once_with(input_data)
    strategy.generate_candidate.assert_awaited_once_with(input_data, existing_output=prod_output)


# ---------------------------------------------------------------------------
# save_review
# ---------------------------------------------------------------------------

def test_save_review_writes_file(tmp_path: Path) -> None:
    workflow = OracleWorkflow(
        strategy=MagicMock(),
        input_source=MagicMock(),
        out_dir=tmp_path,
    )
    items = [{"entity": "Order", "field": "id", "action": "approve"}]
    path = workflow.save_review(items, fixture_id="case1", generated_at="2026-05-27")

    assert path is not None
    data = json.loads(path.read_text())
    assert data["fixture_id"] == "case1"
    assert data["needs_review"] == items


def test_save_review_returns_none_for_empty_items(tmp_path: Path) -> None:
    workflow = OracleWorkflow(
        strategy=MagicMock(),
        input_source=MagicMock(),
        out_dir=tmp_path,
    )
    result = workflow.save_review([], fixture_id="case1")
    assert result is None


# ---------------------------------------------------------------------------
# prompt_version propagation
# ---------------------------------------------------------------------------

async def test_prompt_version_stored_in_fixture(tmp_path: Path) -> None:
    strategy = _make_strategy({})
    workflow = OracleWorkflow(
        strategy=strategy,
        input_source=_make_input_source("case1", {}),
        prompt_version="crud.oracle.v2",
        out_dir=tmp_path,
    )

    fixture = await workflow.run_case("case1")
    assert fixture.prompt_version == "crud.oracle.v2"
