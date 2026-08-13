"""CI gate — fail if eval report metrics exceed thresholds.

Reads eval_report.json and exits with code 1 if any threshold is violated.
Prints a per-route table so engineers can see exactly which route failed.

Usage:
    python -m evals.code_analysis.diagrams.crud_matrix.gate \\
        --report eval_report.json \\
        [--min-precision 0.85] [--min-recall 0.85] [--max-hallucination 0.05]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


_DEFAULT_MIN_PRECISION = 0.85
_DEFAULT_MIN_RECALL = 0.85
_DEFAULT_MAX_HALLUCINATION = 0.05


def main() -> None:
    parser = argparse.ArgumentParser(description="CRUD Matrix eval CI gate")
    parser.add_argument("--report", default="eval_report.json")
    parser.add_argument("--min-precision", type=float, default=_DEFAULT_MIN_PRECISION)
    parser.add_argument("--min-recall", type=float, default=_DEFAULT_MIN_RECALL)
    parser.add_argument("--max-hallucination", type=float, default=_DEFAULT_MAX_HALLUCINATION)
    args = parser.parse_args()

    report_path = Path(args.report)
    if not report_path.exists():
        print(f"[gate] ERROR: report not found: {report_path}", file=sys.stderr)
        sys.exit(2)

    report = json.loads(report_path.read_text())
    summary = report.get("summary", {})
    routes = report.get("routes", [])

    # Per-route table
    print(f"\n{'fixture_id':<40} {'P':>6} {'R':>6} {'F1':>6} {'hall':>6} {'op_acc':>7}")
    print("-" * 75)
    route_failures: list[str] = []
    for r in routes:
        fid = r["fixture_id"]
        p, rec, f1 = r["precision"], r["recall"], r["f1"]
        hall, op_acc = r["hallucination_rate"], r["op_accuracy"]
        fail = (
            p < args.min_precision
            or rec < args.min_recall
            or hall > args.max_hallucination
        )
        flag = " ✗" if fail else ""
        print(f"{fid:<40} {p:>6.3f} {rec:>6.3f} {f1:>6.3f} {hall:>6.3f} {op_acc:>7.3f}{flag}")
        if fail:
            route_failures.append(fid)

    # Aggregate summary
    avg_p = summary.get("precision", 0.0)
    avg_r = summary.get("recall", 0.0)
    avg_hall = summary.get("hallucination_rate", 0.0)
    print("-" * 75)
    print(
        f"{'AVERAGE':<40} {avg_p:>6.3f} {avg_r:>6.3f} "
        f"{summary.get('f1', 0.0):>6.3f} {avg_hall:>6.3f} "
        f"{summary.get('op_accuracy', 0.0):>7.3f}"
    )

    failures: list[str] = []
    if avg_p < args.min_precision:
        failures.append(f"precision {avg_p:.3f} < {args.min_precision}")
    if avg_r < args.min_recall:
        failures.append(f"recall {avg_r:.3f} < {args.min_recall}")
    if avg_hall > args.max_hallucination:
        failures.append(f"hallucination_rate {avg_hall:.3f} > {args.max_hallucination}")

    if failures:
        print("\n[gate] FAILED:")
        for msg in failures:
            print(f"  • {msg}")
        if route_failures:
            print(f"  routes: {', '.join(route_failures)}")
        sys.exit(1)
    else:
        print(f"\n[gate] PASSED ({summary.get('route_count', 0)} routes)")


if __name__ == "__main__":
    main()
