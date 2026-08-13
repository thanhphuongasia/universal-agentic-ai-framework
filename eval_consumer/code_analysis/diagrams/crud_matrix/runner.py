"""Phase 2 — CRUD Matrix eval runner.

Loads oracle fixtures, calls the production target (Sonnet CRUD matrix phase),
compares output via StructuredScorer normalization logic, and writes
an EvalReport JSON.

Usage:
    python -m evals.code_analysis.diagrams.crud_matrix.runner \\
        --fixtures artifacts/eval/oracle_fixtures/crud_matrix/ \\
        --target   <import.path.to.CRUDTarget>                  \\
        --out      eval_report.json
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import time
from pathlib import Path

from .models import CRUDFixture, EvalReport, RouteMetrics
from .normalizer import normalize_field, normalize_op


def _load_fixtures(fixtures_dir: Path) -> list[CRUDFixture]:
    fixtures = []
    for p in sorted(fixtures_dir.glob("*.json")):
        if p.name.endswith(".review.json"):
            continue
        fixtures.append(CRUDFixture.from_dict(json.loads(p.read_text())))
    return fixtures


def _compute_route_metrics(
    actual_cells: dict,          # {entity: {field: op}} from production target
    fixture: CRUDFixture,
) -> RouteMetrics:
    """Compare actual vs oracle expected with CRUD normalization."""
    # Normalize expected: entity_lower -> field_norm -> op_norm
    exp: dict[str, dict[str, str]] = {}
    for entity, fmap in fixture.cells.items():
        exp[entity.lower()] = {normalize_field(f): normalize_op(c.op) for f, c in fmap.items()}

    # valid vocab: entity_lower -> set[field_norm]
    vocab: dict[str, set[str]] = {
        e.lower(): {normalize_field(f) for f in flist}
        for e, flist in fixture.valid_fields.items()
    }

    # Normalize actual
    act: dict[str, dict[str, str]] = {}
    for entity, fmap in actual_cells.items():
        act[entity.lower()] = {normalize_field(f): normalize_op(str(op)) for f, op in fmap.items()}

    tp = fp = fn = hallucinated = name_matched = op_correct = 0

    for entity, a_inner in act.items():
        e_inner = exp.get(entity, {})
        v_keys = vocab.get(entity, set())

        for fk, av in a_inner.items():
            if v_keys and fk not in v_keys:
                hallucinated += 1
                fp += 1
                continue
            if fk in e_inner:
                name_matched += 1
                if av == e_inner[fk]:
                    tp += 1
                    op_correct += 1
                else:
                    fp += 1
            else:
                fp += 1

    for entity, e_inner in exp.items():
        a_inner = act.get(entity, {})
        for fk in e_inner:
            if fk not in a_inner:
                fn += 1

    total_act = sum(len(v) for v in act.values())
    total_exp = sum(len(v) for v in exp.values())
    precision = tp / total_act if total_act else 0.0
    recall = tp / total_exp if total_exp else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    hall_rate = hallucinated / total_act if total_act else 0.0
    op_acc = op_correct / name_matched if name_matched else 0.0

    return RouteMetrics(
        fixture_id=fixture.fixture_id,
        precision=precision, recall=recall, f1=f1,
        hallucination_rate=hall_rate, op_accuracy=op_acc,
        true_positives=tp, false_positives=fp, false_negatives=fn,
        hallucinated=hallucinated, name_matched=name_matched, op_correct=op_correct,
    )


async def _run(args: argparse.Namespace) -> None:
    fixtures_dir = Path(args.fixtures)
    out_path = Path(args.out)

    fixtures = _load_fixtures(fixtures_dir)
    if not fixtures:
        print(f"[runner] No fixtures found in {fixtures_dir}")
        return

    # Load production target dynamically
    # Target must implement: async def run(route_context: dict) -> dict[str, dict[str, str]]
    #   where return value is {entity: {field: op}}
    target_fn = None
    if args.target:
        module_path, _, fn_name = args.target.rpartition(".")
        mod = importlib.import_module(module_path)
        target_fn = getattr(mod, fn_name)

    report = EvalReport(prompt_version=args.prompt_version or "")
    total = len(fixtures)

    for i, fixture in enumerate(fixtures, 1):
        print(f"[runner] {i}/{total} {fixture.fixture_id} …", end=" ", flush=True)
        t0 = time.monotonic()

        if target_fn is not None:
            actual_cells = await target_fn(fixture.base.input_data)
        else:
            # Dry-run: compare fixture expected against itself (should be perfect)
            actual_cells = {
                entity: {f: c.op for f, c in fmap.items()}
                for entity, fmap in fixture.cells.items()
            }

        metrics = _compute_route_metrics(actual_cells, fixture)
        report.routes.append(metrics)
        elapsed = time.monotonic() - t0
        print(
            f"F1={metrics.f1:.3f} P={metrics.precision:.3f} "
            f"R={metrics.recall:.3f} hall={metrics.hallucination_rate:.3f} "
            f"({elapsed:.1f}s)"
        )

    out_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    print(f"\n[runner] Report → {out_path}")
    print(
        f"[runner] Summary: P={report.avg_precision:.3f} R={report.avg_recall:.3f} "
        f"F1={report.avg_f1:.3f} hall={report.avg_hallucination_rate:.3f} "
        f"op_acc={report.avg_op_accuracy:.3f} ({total} routes)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run CRUD Matrix eval against oracle fixtures")
    parser.add_argument("--fixtures", default="artifacts/eval/oracle_fixtures/crud_matrix",
                        help="Directory of oracle fixture JSON files")
    parser.add_argument("--target", default="",
                        help="Dotted path to async target function: "
                             "module.path.run_crud_matrix_phase")
    parser.add_argument("--out", default="eval_report.json", help="Output report path")
    parser.add_argument("--prompt-version", default="", help="Prompt version tag for report")
    asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    main()
