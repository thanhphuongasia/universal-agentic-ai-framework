"""
Code Analysis — UAAF Example (refactored)
==========================================
Uses: OpenAI (real) + PromptRegistry (YAML versioning) + ToolRegistry (function calling)

Demonstrates:
  • Phase ingestion: ast-based Python class extraction
  • Multi-agent: one ClassAnalysisAgent per class, uses YAML prompt versioning
  • Parallel execution: asyncio.Semaphore with configurable concurrency
  • Shared knowledge: GraphBackbone stores class context across agents
  • LLM summary: summarize_codebase prompt rendered by PromptRegistry
  • Tool calling: post-analysis queries via ToolRegistry handlers

Run:
    OPENAI_API_KEY=sk-... python -m examples.code_analysis.main
    python -m examples.code_analysis.main                       # demo mode
    python -m examples.code_analysis.main --target uaaf/        # analyse the framework
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

from examples.code_analysis.agents import (
    AgentFactory,
    CodebaseAnalysisOrchestrator,
    build_provider,
)
from examples.code_analysis.ingestion import ClassInfo, PythonIngester
from examples.code_analysis.tools import build_code_registry
from uaaf.knowledge.graph.backbone import GraphBackbone
from uaaf.prompts.registry import PromptRegistry
from uaaf.runtime.context import ContextScope, ExecutionContext


def print_separator(title: str = "") -> None:
    width = 64
    if title:
        pad = (width - len(title) - 2) // 2
        print(f"\n{'─' * pad} {title} {'─' * pad}")
    else:
        print(f"\n{'─' * width}")


# ---------------------------------------------------------------------------
# Class ingestion helpers
# ---------------------------------------------------------------------------

def build_mock_classes() -> list[ClassInfo]:
    """Ingest real classes from the uaaf/ source tree, or fall back to synthetic data."""
    repo_root = Path(__file__).parent.parent.parent
    uaaf_dir = repo_root / "uaaf"

    if uaaf_dir.exists():
        ingester = PythonIngester()
        classes = ingester.ingest_directory(uaaf_dir)
        print(f"  📂 Ingested from: {uaaf_dir}")
        return classes

    print("  ⚠️  uaaf/ not found, using synthetic class data")
    return _synthetic_classes()


def _synthetic_classes() -> list[ClassInfo]:
    """Minimal synthetic dataset for environments without the uaaf/ tree."""
    from examples.code_analysis.ingestion import MethodInfo

    base = ClassInfo(
        name="BaseAgent", file_path="uaaf/execution/agent.py", module="agent",
        line_start=1, line_end=120, docstring="Base class for all UAAF agents.",
        base_classes=["ABC"],
        methods=[
            MethodInfo("execute", ["task", "context"], "Run agent.", 20, is_async=True),
            MethodInfo("_execute", ["task", "context"], "", 5, is_async=True),
            MethodInfo("__init__", ["agent_id", "cost_tracker"], "Init.", 10),
        ],
    )
    router = ClassInfo(
        name="ModelRouter", file_path="uaaf/providers/router.py", module="router",
        line_start=1, line_end=80, docstring="Routes requests by model tier.",
        base_classes=[],
        methods=[
            MethodInfo("complete", ["request"], "Complete a request.", 25, is_async=True),
            MethodInfo("route", ["tier"], "", 8),
            MethodInfo("_model_to_tier", ["model"], "", 10),
            MethodInfo("record_failure", ["provider_id"], "", 3),
            MethodInfo("record_success", ["provider_id"], "", 3),
        ],
    )
    cb = ClassInfo(
        name="CircuitBreaker", file_path="uaaf/providers/circuit_breaker.py",
        module="circuit_breaker",
        line_start=1, line_end=60, docstring="",
        base_classes=[],
        methods=[
            MethodInfo("is_available", [], "", 12),
            MethodInfo("record_failure", [], "", 8),
            MethodInfo("record_success", [], "", 6),
            MethodInfo("__init__", ["failure_threshold", "recovery_timeout"], "", 5),
        ],
    )
    return [base, router, cb]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main(target_dir: Path | None = None) -> None:
    # ── Prompt registry info ─────────────────────────────────────────────────
    prompts_root = Path(__file__).parent.parent.parent / "prompts"
    registry = PromptRegistry(prompts_root=prompts_root)
    cfg = registry.load("code_analysis", "v1")

    print_separator("UAAF Code Analysis — OpenAI + PromptRegistry + Tools")
    print("\n  Prompt config : prompts/code_analysis/v1.yaml")
    print(f"  Version       : {cfg.version}  |  Model: {cfg.model}  |  Temp: {cfg.temperature}")
    print(f"  Prompts       : {list(cfg.prompts)}")
    print(f"  Tools defined : {[t.name for t in cfg.tools]}")

    # ── 1. Ingestion phase ───────────────────────────────────────────────────
    print_separator("Phase 1: Ingestion")
    t0 = time.monotonic()

    ingester = PythonIngester()
    if target_dir and target_dir.exists():
        print(f"  📂 Target: {target_dir}")
        classes = ingester.ingest_directory(target_dir, max_files=50)
    else:
        classes = build_mock_classes()

    ingest_time = time.monotonic() - t0
    print(f"  ✅ Extracted {len(classes)} classes in {ingest_time:.3f}s")

    print("\n  Sample classes (top 5 by complexity):")
    for cls in sorted(classes, key=lambda c: c.complexity_score, reverse=True)[:5]:
        print(f"    • {cls.summary()}")

    if not classes:
        print("  No classes found. Exiting.")
        return

    # ── 2. Provider + orchestrator ───────────────────────────────────────────
    print_separator("Phase 2: Multi-Agent Analysis")
    llm = build_provider()   # for codebase summary step; AgentFactory builds its own
    concurrency = min(8, len(classes))
    print(f"  🤖 Spawning {len(classes)} agents (max {concurrency} concurrent)...")
    print("  System prompt : prompts/code_analysis/v1.yaml → prompts.analyze_class.system\n")

    shared_backbone = GraphBackbone()
    orchestrator = CodebaseAnalysisOrchestrator(
        shared_backbone=shared_backbone,
        max_concurrency=concurrency,
    )
    factory = AgentFactory()

    base_ctx = ExecutionContext(
        scope=ContextScope(user_id="analyst", session_id="code-analysis-1", domain="codebase"),
        correlation_id="ca-demo-001",
    )

    # ── 3. Run all agents in parallel ────────────────────────────────────────
    report = await orchestrator.analyse(
        classes=classes,
        base_context=base_ctx,
        agent_factory=factory,
    )

    # ── 4. Results ───────────────────────────────────────────────────────────
    print_separator("Phase 3: Results")
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
    print(f"\n  📝 Docstring coverage: {has_doc}/{len(report.class_reports)} ({pct:.0f}%)")

    total_async = sum(r.get("async_method_count", 0) for r in report.class_reports)
    print(f"  ⚡ Total async methods: {total_async}")

    # ── 5. Refactor queue ────────────────────────────────────────────────────
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

    # ── 6. LLM Codebase Summary (PromptRegistry) ─────────────────────────────
    print_separator("LLM Summary  [summarize_codebase]")
    print("  System prompt : prompts/code_analysis/v1.yaml → prompts.summarize_codebase.system\n")

    high_count = len(high)
    doc_pct = round(pct, 1)
    summarize_request = registry.build_request(
        cfg, "summarize_codebase",
        include_tools=False,
        total_classes=len(report.class_reports),
        high_count=high_count,
        high=complexity_dist.get("HIGH", 0),
        medium=complexity_dist.get("MEDIUM", 0),
        low=complexity_dist.get("LOW", 0),
        doc_pct=doc_pct,
        async_count=total_async,
    )
    summary_response = await llm.complete(summarize_request)
    print(summary_response.content)

    # ── 7. Tool demos (direct calls) ─────────────────────────────────────────
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

    # ── 8. GraphBackbone knowledge query ─────────────────────────────────────
    print_separator("GraphBackbone Knowledge Query")
    from uaaf.knowledge.context_assembler import ContextAssembler
    assembler = ContextAssembler(shared_backbone)
    assembled = await assembler.assemble(
        query="async",           # substring match — finds classes with async methods
        scope_key="codebase",
        budget_tokens=500,
    )
    print("  Query: 'async'  (finds classes with async methods)")
    print(f"  Retrieved {assembled.token_count} tokens from graph ({len(assembled.source_ids)} nodes)")
    if assembled.text:
        preview = assembled.text[:400].replace("\n", " ")
        print(f"  Preview: {preview}...")

    print_separator()
    print(f"  Total time : {report.elapsed_seconds:.2f}s (parallel execution)")
    print(f"  Throughput : {len(classes) / max(report.elapsed_seconds, 0.001):.0f} classes/sec")
    print("  Prompt versioning: bump to v2.yaml to iterate prompts without code changes")
    print("  Tool calling:      LLM chooses tools from YAML schema, Python executes them\n")


if __name__ == "__main__":
    target = None
    if len(sys.argv) > 2 and sys.argv[1] == "--target":
        target = Path(sys.argv[2])
    asyncio.run(main(target_dir=target))
