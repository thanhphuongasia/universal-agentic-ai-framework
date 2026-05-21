"""Workflow states for the code analysis pipeline.

Three states wired through WorkflowEngine:
  ingest → analyse → summarize

Each state is a plain @dataclass implementing the IState Protocol — no
framework inheritance required. WorkflowEngine checkpoints after every
state so the pipeline is resume-safe if interrupted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from examples.code_analysis.agents import (
    AgentFactory,
    CodebaseAnalysisOrchestrator,
    CodebaseReport,
    build_provider,
)
from examples.code_analysis.ingestion import PythonIngester
from ryuu.knowledge.graph.backbone import GraphBackbone
from ryuu.prompts.registry import PromptRegistry
from ryuu_workflow.context import ExecutionContext
from ryuu_workflow.state_machine import StateTransition

_PROMPTS_ROOT = Path(__file__).parent / "prompts"


@dataclass
class IngestState:
    """Phase 1 — parse Python source files → list[ClassInfo]."""

    state_id: str = "ingest"
    max_files: int = 50

    async def execute(self, input: Any, context: ExecutionContext) -> StateTransition:
        target = Path(input) if isinstance(input, str) else input
        ingester = PythonIngester()
        if isinstance(target, Path) and target.exists():
            classes = ingester.ingest_directory(target, max_files=self.max_files)
        else:
            repo_root = Path(__file__).parent.parent.parent
            classes = ingester.ingest_directory(repo_root / "ryuu")
        print(f"  [ingest]    {len(classes)} classes extracted")
        return StateTransition(next_state="analyse", output=classes)


@dataclass
class AnalyseState:
    """Phase 2 — parallel per-class agent analysis → CodebaseReport.

    backbone is public so callers can share it with a later GraphBackbone query.
    """

    state_id: str = "analyse"
    max_concurrency: int = 8
    backbone: GraphBackbone = field(default_factory=GraphBackbone)

    async def execute(self, input: Any, context: ExecutionContext) -> StateTransition:
        classes = input
        orchestrator = CodebaseAnalysisOrchestrator(
            shared_backbone=self.backbone,
            max_concurrency=min(self.max_concurrency, max(1, len(classes))),
        )
        report = await orchestrator.analyse(classes, context, AgentFactory())
        print(
            f"  [analyse]   {len(report.class_reports)}/{report.total_classes}"
            f" classes in {report.elapsed_seconds:.2f}s"
        )
        return StateTransition(next_state="summarize", output=report)


@dataclass
class SummarizeState:
    """Phase 3 — LLM codebase summary → plain string."""

    state_id: str = "summarize"

    async def execute(self, input: Any, context: ExecutionContext) -> StateTransition:
        report: CodebaseReport = input
        llm = build_provider()
        registry = PromptRegistry(prompts_root=_PROMPTS_ROOT)
        cfg = registry.load("code_analysis", "v1")

        complexity_dist: dict[str, int] = {}
        for r in report.class_reports:
            key = r.get("complexity", "LOW")
            complexity_dist[key] = complexity_dist.get(key, 0) + 1

        has_doc = sum(1 for r in report.class_reports if r.get("has_docstring"))
        doc_pct = (has_doc / len(report.class_reports) * 100) if report.class_reports else 0.0
        total_async = sum(r.get("async_method_count", 0) for r in report.class_reports)

        request = registry.build_request(
            cfg, "summarize_codebase",
            include_tools=False,
            total_classes=len(report.class_reports),
            high_count=len(report.high_priority()),
            high=complexity_dist.get("HIGH", 0),
            medium=complexity_dist.get("MEDIUM", 0),
            low=complexity_dist.get("LOW", 0),
            doc_pct=round(doc_pct, 1),
            async_count=total_async,
        )
        response = await llm.complete(request)
        print(f"  [summarize] {len(response.content)} char summary generated")
        return StateTransition(next_state=None, output=response.content)
