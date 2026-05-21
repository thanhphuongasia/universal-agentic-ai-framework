"""
Code Analysis — RYUU Example (WorkflowEngine edition)
======================================================
Demonstrates:
  • WorkflowEngine: 3-state pipeline  ingest → analyse → summarize
  • Checkpoint-per-state: resume-safe if interrupted (SIGKILL-safe)
  • Multi-agent: one ClassAnalysisAgent per class via AgentPool.fan_out
  • PromptRegistry: YAML versioning for prompt templates
  • ToolRegistry: function calling handlers
  • GraphBackbone: shared knowledge across agents, queryable after run

Run:
    OPENAI_API_KEY=sk-... python -m examples.code_analysis.main
    python -m examples.code_analysis.main                       # demo mode
    python -m examples.code_analysis.main --target ryuu/        # analyse the framework
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

from examples.code_analysis.tools import build_code_registry
from examples.code_analysis.workflow import AnalyseState, IngestState, SummarizeState
from ryuu.knowledge.context_assembler import ContextAssembler
from ryuu_workflow.context import ContextScope, ExecutionContext
from ryuu_workflow.engine import WorkflowEngine
from ryuu_workflow.state_machine import Workflow
from ryuu_workflow.stores.in_memory import InMemoryCheckpointStore


def print_separator(title: str = "") -> None:
    width = 64
    if title:
        pad = (width - len(title) - 2) // 2
        print(f"\n{'─' * pad} {title} {'─' * pad}")
    else:
        print(f"\n{'─' * width}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main(target_dir: Path | None = None) -> None:
    print_separator("RYUU Code Analysis — WorkflowEngine + Multi-Agent")
    print("\n  Pipeline : ingest → analyse → summarize")
    print("  Engine   : WorkflowEngine (checkpoint-per-state, SIGKILL-safe)")
    print("  Prompts  : examples/code_analysis/prompts/code_analysis/v1.yaml\n")

    # ── 1. Build workflow ────────────────────────────────────────────────────
    print_separator("Pipeline Run")

    # AnalyseState holds the shared GraphBackbone — extract it after the run
    # so the GraphBackbone query in section 5 uses the same populated store.
    analyse_state = AnalyseState()

    workflow = Workflow(
        workflow_id="code-analysis-001",
        states={
            "ingest": IngestState(),
            "analyse": analyse_state,
            "summarize": SummarizeState(),
        },
        initial_state="ingest",
        terminal_states=frozenset(),
    )

    store = InMemoryCheckpointStore()
    engine = WorkflowEngine(checkpoint_store=store)

    ctx = ExecutionContext(
        scope=ContextScope(user_id="analyst", session_id="code-analysis-1", domain="codebase"),
        correlation_id="ca-demo-001",
    )

    t0 = time.monotonic()
    wf_result = await engine.run(
        workflow,
        initial_input=str(target_dir) if target_dir else None,
        context=ctx,
    )
    elapsed = time.monotonic() - t0

    print(f"\n  status={wf_result.status.value}  checkpoints={wf_result.checkpoints_saved}  time={elapsed:.2f}s")

    if wf_result.status.value != "completed":
        print(f"  ERROR: {wf_result.error}")
        return

    # ── 2. Extract results from checkpoints ──────────────────────────────────
    # history[0] = ingest output, history[1] = analyse output, history[2] = summarize output
    history = await store.load_history("code-analysis-001")
    classes = history[0].output
    report = history[1].output
    summary_text: str = wf_result.output

    # ── 3. Results ───────────────────────────────────────────────────────────
    print_separator("Results")
    report.print_summary()

    complexity_dist: dict[str, int] = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for r in report.class_reports:
        key = r.get("complexity", "LOW")
        complexity_dist[key] = complexity_dist.get(key, 0) + 1

    print("\n  Complexity distribution:")
    for level, count in complexity_dist.items():
        bar = "█" * count
        print(f"    {level:6s} [{bar:<30s}] {count}")

    has_doc = sum(1 for r in report.class_reports if r.get("has_docstring"))
    pct = (has_doc / len(report.class_reports) * 100) if report.class_reports else 0
    print(f"\n  Docstring coverage : {has_doc}/{len(report.class_reports)} ({pct:.0f}%)")

    total_async = sum(r.get("async_method_count", 0) for r in report.class_reports)
    print(f"  Async methods total: {total_async}")

    # ── 4. Refactor queue ────────────────────────────────────────────────────
    print_separator("Refactor Queue (HIGH priority)")
    high = report.high_priority()
    if high:
        for i, r in enumerate(high, 1):
            print(f"\n  {i}. {r['class']} [{r.get('module', '?')}] (score={r.get('complexity_score', '?')})")
            for issue in r.get("issues", []):
                print(f"     • {issue}")
            print(f"     → {r.get('suggestion', '')}")
    else:
        print("  ✅ No high-priority refactors found!")

    # ── 5. LLM Summary ───────────────────────────────────────────────────────
    print_separator("LLM Summary  [summarize_codebase]")
    print(summary_text)

    # ── 6. Tool demos (direct calls) ─────────────────────────────────────────
    print_separator("Tool Calls — Direct Demo")
    print("  (Shows what the LLM would receive as tool results)\n")

    tool_registry = build_code_registry(classes, report.class_reports)
    first_module = classes[0].module if classes else "agent"
    first_class = classes[0].name if classes else "BaseAgent"

    tool_demos: list[dict[str, Any]] = [
        {"id": "tc1", "function": {"name": "find_refactor_candidates",
                                   "arguments": {"min_complexity_score": 30}}},
        {"id": "tc2", "function": {"name": "get_module_summary",
                                   "arguments": {"module_name": first_module}}},
        {"id": "tc3", "function": {"name": "get_class_details",
                                   "arguments": {"class_name": first_class}}},
    ]
    for demo in tool_demos:
        fn_name = demo["function"]["name"]
        fn_args = demo["function"]["arguments"]
        result_str = await tool_registry.run(demo)
        result_data = json.loads(result_str)
        print(f"  🔧 {fn_name}({fn_args})")
        print(f"     → {json.dumps(result_data, indent=6)[:400]}")
        print()

    # ── 7. GraphBackbone knowledge query ─────────────────────────────────────
    print_separator("GraphBackbone Knowledge Query")
    assembler = ContextAssembler(analyse_state.backbone)
    assembled = await assembler.assemble(
        query="async",
        scope_key="codebase",
        budget_tokens=500,
    )
    print("  Query: 'async'  (finds classes with async methods)")
    print(f"  Retrieved {assembled.token_count} tokens from graph ({len(assembled.source_ids)} nodes)")
    if assembled.text:
        preview = assembled.text[:400].replace("\n", " ")
        print(f"  Preview: {preview}...")

    # ── 8. Checkpoint audit ───────────────────────────────────────────────────
    print_separator("Checkpoint Audit")
    print(f"  {len(history)} checkpoints saved by WorkflowEngine:\n")
    for cp in history:
        output_summary = (
            f"{len(cp.output)} classes" if isinstance(cp.output, list)
            else f"CodebaseReport({cp.output.total_classes} classes)" if hasattr(cp.output, "total_classes")
            else f"{len(cp.output)} chars"
        )
        print(f"    seq={cp.sequence}  state={cp.state_id:<12s}  output={output_summary}")

    print_separator()
    print(f"  Total time : {elapsed:.2f}s")
    print(f"  Throughput : {len(classes) / max(elapsed, 0.001):.0f} classes/sec")
    print("  WorkflowEngine resumed from any checkpoint after SIGKILL\n")


if __name__ == "__main__":
    target = None
    if len(sys.argv) > 2 and sys.argv[1] == "--target":
        target = Path(sys.argv[2])
    asyncio.run(main(target_dir=target))
