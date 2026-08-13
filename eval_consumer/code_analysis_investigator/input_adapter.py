"""Adapter: convert eval_diff + route_context → generic InputBundle.

Called by run_local.py to bridge ryuu-eval CRUD matrix output to the
generic ryuu-eval-investigator framework.
"""

from __future__ import annotations

from typing import Any

from ryuu_eval_investigator import InputBundle


def build_bundle(
    case_id: str,
    route_id: str,
    route_context_json: dict[str, Any],
    production_output: dict[str, Any],
    ground_truth: list[dict[str, Any]],
    eval_diff: dict[str, Any],
    repo_path: str,
    project_id: str = "",
) -> InputBundle:
    """CRUD-matrix eval failure → InputBundle."""
    return InputBundle(
        case_id=case_id,
        target_id=route_id,
        payload={
            "route_context_json": route_context_json,
            "production_output": production_output,
            "ground_truth": ground_truth,
        },
        diff=eval_diff,
        repo_path=repo_path,
        project_id=project_id,
    )
