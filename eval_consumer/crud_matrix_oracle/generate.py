"""Oracle fixture generator CLI — CRUD matrix domain.

Usage:
    python -m eval_consumer.crud_matrix_oracle.generate \\
        --case artifacts/eval/cases/crud_matrix_llm/case1_happy_path.yml \\
        --out  artifacts/eval/oracle_fixtures/crud_matrix/ \\
        [--force]
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from ryuu_eval_oracle import FileInputSource, OracleWorkflow

from .strategy import CrudMatrixOracleStrategy


def _build_review_items(expected: dict) -> list[dict]:
    items = []
    for entity, fields in expected.get("cells", {}).items():
        for field_name, cell in fields.items():
            if cell.get("confidence") in ("low", "medium"):
                items.append({
                    "entity": entity,
                    "field": field_name,
                    "op": cell.get("op", ""),
                    "confidence": cell.get("confidence"),
                    "oracle_why": cell.get("oracle_why", ""),
                    "action": None,
                    "corrected_op": None,
                })
    return items


async def _run(args: argparse.Namespace) -> None:
    case_path = Path(args.case)
    out_dir = Path(args.out)
    case_id = args.fixture_id or case_path.stem

    out_path = out_dir / f"{case_id}.json"
    if out_path.exists() and not args.force:
        print(f"[oracle] Fixture already exists: {out_path}  (use --force to overwrite)")
        return

    strategy = CrudMatrixOracleStrategy(framework=args.framework, model=args.model)
    workflow = OracleWorkflow(
        strategy=strategy,
        input_source=FileInputSource(case_path.parent, ext=case_path.suffix),
        prompt_version=strategy.prompt_version,
        out_dir=out_dir,
    )

    print(f"[oracle] Calling {args.model} for '{case_id}'…")
    fixture = await workflow.run_case(case_id)

    review_items = _build_review_items(fixture.expected)
    if review_items:
        workflow.save_review(review_items, fixture_id=case_id)
        print(f"[oracle] {len(review_items)} cell(s) need review → {out_dir}/{case_id}.review.json")
    else:
        print("[oracle] All cells high-confidence — no review file needed.")
    print(f"[oracle] Fixture written → {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate oracle fixture from eval case YAML")
    parser.add_argument("--case", required=True, help="Path to eval case YAML")
    parser.add_argument("--out", default="artifacts/eval/oracle_fixtures/crud_matrix",
                        help="Output directory for fixture JSON")
    parser.add_argument("--fixture-id", help="Override fixture ID (default: case stem)")
    parser.add_argument("--framework", default="java_spring", choices=["java_spring"],
                        help="Framework variant (determines oracle prompt)")
    parser.add_argument("--model", default="claude-opus-4-7", help="Oracle model override")
    parser.add_argument("--force", action="store_true", help="Overwrite existing fixture")
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
