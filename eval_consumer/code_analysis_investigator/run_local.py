"""Local debug runner — investigates one route using AgentSdkBackend.

Auth: ANTHROPIC_API_KEY env var OR Claude Code subscription (`claude login`).

Run with a sample fixture:
    cd uaaf-framework
    python -m eval_consumer.code_analysis_investigator.run_local \\
        --case sample_case.json \\
        --repo-path /absolute/path/to/spring-crud-route-entity-detection
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import yaml

from ryuu_eval_investigator import InputBundle, create_store
from ryuu_eval_investigator.backends.agent_sdk_backend import AgentSdkBackend
from ryuu_eval_investigator.prompts import compose, load_base_prompt

from .input_adapter import build_bundle

RULES_PATH = Path(__file__).parent / "rules.yml"


def load_rules() -> dict:
    return yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))


def render_domain_rules(rules: dict) -> str:
    """Render domain rules.yml into the slot text injected into base prompt."""
    issue_types = "\n".join(
        f"  {name:<22} — {meta['description']}"
        for name, meta in rules["issue_types"].items()
    )
    return (
        f"For each item in diff.missing_fields, classify into exactly one issue_type:\n"
        f"{issue_types}\n\n"
        f"Investigation order (stop when conclusive):\n"
        f"{rules['investigation_order']}\n\n"
        f"Budget: at most {rules['tool_cap_per_field']} tool calls per field."
    )


async def main_async(case_path: str, repo_path: str, suite_id: str) -> None:
    case = json.loads(Path(case_path).read_text(encoding="utf-8"))

    # 1. Adapt → InputBundle
    bundle = build_bundle(
        case_id=case["case_id"],
        route_id=case["route_id"],
        route_context_json=case.get("route_context_json", {}),
        production_output=case.get("production_output", {}),
        ground_truth=case.get("ground_truth", []),
        eval_diff=case.get("eval_diff", {}),
        repo_path=repo_path,
        project_id=case.get("project_id", ""),
    )

    # 2. Compose system prompt: base + domain rules
    rules = load_rules()
    base = load_base_prompt("v1")
    system_prompt = compose(base, render_domain_rules(rules))

    # 3. Run backend with streaming
    print(f"=== Investigating: {bundle.target_id} (case_id={bundle.case_id}) ===")
    backend = AgentSdkBackend(stream_to_stdout=True)
    report = await backend.investigate(bundle, system_prompt=system_prompt)

    # 4. Persist
    store = create_store()
    store.save(bundle.case_id, suite_id, report)

    # 5. Summary
    print(f"\n{'=' * 60}")
    print(f"Findings   : {len(report.findings)}")
    print(f"Summary    : {report.summary}")
    print(f"Tool calls : {report.tool_calls_used}")
    print(f"Cost (est) : ${report.cost_usd:.5f}")
    for f in report.findings:
        print(f"  - {f.entity}.{f.field} → {f.issue_type} ({f.confidence})")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True, help="Path to case JSON")
    parser.add_argument("--repo-path", required=True, help="Absolute path to source repo")
    parser.add_argument("--suite-id", default="code_analysis_crud_matrix")
    args = parser.parse_args()
    asyncio.run(main_async(args.case, args.repo_path, args.suite_id))


if __name__ == "__main__":
    main()
