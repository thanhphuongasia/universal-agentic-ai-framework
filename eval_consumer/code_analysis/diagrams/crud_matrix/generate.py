"""Phase 1 — Oracle fixture generator for CRUD Matrix eval.

Reads an eval case YAML (artifacts/eval/cases/crud_matrix_llm/),
calls the Opus oracle, and writes a CRUDFixture JSON to
artifacts/eval/oracle_fixtures/crud_matrix/.

Usage:
    python -m evals.code_analysis.diagrams.crud_matrix.generate \\
        --case artifacts/eval/cases/crud_matrix_llm/case1_happy_path.yml \\
        --out  artifacts/eval/oracle_fixtures/crud_matrix/            \\
        [--force]
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date
from pathlib import Path

import yaml

from ryuu_eval_core.oracle import OracleFixture, OracleWorkflow
from ryuu_providers_anthropic import AnthropicProvider

from .models import CRUDCell, CRUDFixture
from .normalizer import normalize_op

_PROMPT_DIR = Path(__file__).parent / "prompts"
_PROMPT_VERSION = "crud_matrix_oracle.v1"
_DEFAULT_OUT = Path("artifacts/eval/oracle_fixtures/crud_matrix")


def _load_prompt(framework: str) -> dict:
    path = _PROMPT_DIR / f"{framework}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Oracle prompt not found: {path}")
    with open(path) as f:
        return yaml.safe_load(f)


def _extract_valid_fields(route_context: dict) -> dict[str, list[str]]:
    """Build {entity_short_name: [db_column_or_field]} from route_context.entities."""
    valid: dict[str, list[str]] = {}
    for ent in route_context.get("entities", []):
        short = ent.get("short_name") or ent.get("fqn", "").rsplit(".", 1)[-1]
        cols = [
            f.get("db_column") or f.get("name", "")
            for f in ent.get("fields", [])
            if f.get("db_column") or f.get("name")
        ]
        valid[short] = cols
    return valid


def _parse_cells(raw_cells: dict) -> dict[str, dict[str, CRUDCell]]:
    result: dict[str, dict[str, CRUDCell]] = {}
    for entity, fields in raw_cells.items():
        result[entity] = {
            fname: CRUDCell(
                op=normalize_op(cell.get("op", "")),
                confidence=cell.get("confidence", "high"),
                oracle_why=cell.get("why", ""),
            )
            for fname, cell in fields.items()
        }
    return result


async def _run(args: argparse.Namespace) -> None:
    case_path = Path(args.case)
    out_dir = Path(args.out)

    with open(case_path) as f:
        case_data = yaml.safe_load(f)

    case_id: str = case_data.get("case_id", case_path.stem)
    fixture_id: str = args.fixture_id or case_id
    framework: str = args.framework

    out_path = out_dir / f"{fixture_id}.json"
    if out_path.exists() and not args.force:
        print(f"[oracle] Fixture exists: {out_path}  (--force to overwrite)")
        return

    route_context: dict = case_data.get("input", {})
    if not isinstance(route_context, dict):
        raise ValueError(f"case.input must be a dict (route_context), got {type(route_context)}")

    prompt_cfg = _load_prompt(framework)
    system: str = prompt_cfg["system"]
    user: str = prompt_cfg["user_template"].replace(
        "{{ route_context_json }}",
        json.dumps(route_context, ensure_ascii=False, indent=2),
    )

    oracle_model: str = args.model or prompt_cfg.get("model", "claude-opus-4-7")
    print(f"[oracle] Calling {oracle_model} for fixture '{fixture_id}'…")

    provider = AnthropicProvider(default_model=oracle_model)
    workflow = OracleWorkflow(provider)

    raw = await workflow.call(system=system, user=user, model=oracle_model)
    raw_cells = raw.get("cells", {})

    valid_fields = _extract_valid_fields(route_context)
    cells = _parse_cells(raw_cells)

    base = OracleFixture(
        fixture_id=fixture_id,
        prompt_version=_PROMPT_VERSION,
        input_data=route_context,
        expected={},
        oracle_model=oracle_model,
        meta={"valid_fields": valid_fields},
    )
    fixture = CRUDFixture(base=base, cells=cells, valid_fields=valid_fields)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(fixture.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[oracle] Fixture written → {out_path}")

    review_items = fixture.review_items()
    review_path = workflow.save_review(
        items=review_items,
        fixture_id=fixture_id,
        out_dir=out_dir,
        generated_at=date.today().isoformat(),
    )
    if review_path:
        print(f"[oracle] {len(review_items)} cell(s) need review → {review_path}")
    else:
        print("[oracle] All cells high-confidence — no review needed.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate CRUD oracle fixture from eval case YAML")
    parser.add_argument("--case", required=True, help="Eval case YAML path")
    parser.add_argument("--out", default=str(_DEFAULT_OUT), help="Output directory")
    parser.add_argument("--fixture-id", dest="fixture_id", help="Override fixture ID")
    parser.add_argument("--framework", default="java_spring", choices=["java_spring"])
    parser.add_argument("--model", default="", help="Oracle model override")
    parser.add_argument("--force", action="store_true", help="Overwrite existing fixture")
    asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    main()
