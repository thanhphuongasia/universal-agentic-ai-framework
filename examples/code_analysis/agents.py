"""
Multi-agent layer for code analysis — refactored to use PromptRegistry + OpenAI.
===============================================================================
Uses: OpenAI (real) + PromptRegistry (YAML versioning) + FakeLLMProvider (demo)

Each ClassAnalysisAgent handles ONE class — they run in parallel via AgentPool.fan_out.
Results are collected into a CodebaseReport by the orchestrator.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from examples.code_analysis.ingestion import ClassInfo
from ryuu._testing.fakes import FakeLLMProvider
from ryuu.execution.agent import AgentResult, BaseAgent, Task
from ryuu.execution.pool import AgentPool
from ryuu.knowledge.context_assembler import ContextAssembler
from ryuu.knowledge.graph.backbone import GraphBackbone
from ryuu.observability.cost import Cost
from ryuu.prompts.registry import PromptRegistry
from ryuu.providers.llm import ILLMProvider, Response, TokenUsage
from ryuu_workflow.context import ExecutionContext

# Prompt registry — loaded once, shared across all agent instances
_PROMPTS_ROOT = Path(__file__).parent / "prompts"
_registry = PromptRegistry(prompts_root=_PROMPTS_ROOT)


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------

def _resp(text: str) -> Response:
    return Response(
        content=text, model="gpt-4o-mini",
        usage=TokenUsage(80, 60), finish_reason="stop",
    )


def build_provider() -> ILLMProvider:
    """Return OpenAIProvider if OPENAI_API_KEY is set, FakeLLMProvider otherwise.

    The returned provider is used for the codebase *summarize* step in main.py.
    Per-class analysis uses AgentFactory which builds its own provider.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        from ryuu.providers.adapters.openai import OpenAIProvider
        print("  🔑 Using OpenAIProvider (OPENAI_API_KEY found)")
        return OpenAIProvider(api_key=api_key)  # type: ignore[return-value]
    else:
        print("  ⚠️  OPENAI_API_KEY not set — using FakeLLMProvider (demo mode)")
        return FakeLLMProvider(responses=[_resp(  # type: ignore[return-value]
            "• Architecture: agent, router, and circuit_breaker modules analyzed\n"
            "• Quality: ~40% docstring coverage; several classes missing class-level docs\n"
            "• Complexity: multiple HIGH classes — consider splitting large methods\n"
            "• Async: significant use of async/await throughout the codebase\n\n"
            "Action items:\n"
            "1. Add class + method docstrings to classes flagged as missing docs\n"
            "2. Refactor long methods (>30 lines) into smaller helpers\n"
            "3. Review HIGH-complexity classes for SRP violations"
        )])


# ---------------------------------------------------------------------------
# Per-class fake LLM — deterministic, used in demo mode only
# ---------------------------------------------------------------------------

def _build_class_llm(cls: ClassInfo) -> FakeLLMProvider:
    """Generate a pre-baked analysis response for one class (demo mode)."""
    issues = []
    if cls.line_count > 100:
        issues.append(f"Large class ({cls.line_count} lines) — consider splitting")
    if len(cls.methods) > 10:
        issues.append(f"Many methods ({len(cls.methods)}) — possible SRP violation")
    if not cls.docstring:
        issues.append("Missing class docstring")
    missing_docs = [m for m in cls.public_methods if not m.docstring]
    if missing_docs:
        issues.append(f"{len(missing_docs)} public method(s) lack docstrings")
    async_methods = [m for m in cls.methods if m.is_async]
    long_methods = [m for m in cls.methods if m.line_count > 30]

    complexity_label = (
        "LOW" if cls.complexity_score < 20
        else "MEDIUM" if cls.complexity_score < 50
        else "HIGH"
    )

    analysis = json.dumps({
        "class": cls.name,
        "module": cls.module,
        "complexity": complexity_label,
        "complexity_score": cls.complexity_score,
        "lines": cls.line_count,
        "method_count": len(cls.methods),
        "async_method_count": len(async_methods),
        "long_methods": [m.name for m in long_methods],
        "public_api_size": len(cls.public_methods),
        "has_docstring": bool(cls.docstring),
        "issues": issues,
        "refactor_priority": "HIGH" if len(issues) >= 2 else "MEDIUM" if issues else "LOW",
        "suggestion": (
            "Extract helper methods and add docstrings." if issues
            else "Class looks clean and well-structured."
        ),
    }, indent=2)

    return FakeLLMProvider(responses=[_resp(analysis)])


# ---------------------------------------------------------------------------
# Single-class agent
# ---------------------------------------------------------------------------

@dataclass
class ClassAnalysisAgent(BaseAgent):
    """Analyzes ONE Python class using PromptRegistry + LLM."""
    llm: ILLMProvider = field(default_factory=build_provider)
    assembler: ContextAssembler = field(
        default_factory=lambda: ContextAssembler(GraphBackbone())
    )
    cls_info: ClassInfo | None = field(default=None)

    async def _execute(self, task: Task, context: ExecutionContext) -> AgentResult:
        cls = self.cls_info
        if cls is None:
            raise ValueError("cls_info not set")

        # 1. Write class info into the shared GraphBackbone
        scope_key = context.scope.domain
        await self.assembler.write(
            observation=cls.to_context_text(),
            scope_key=scope_key,
        )

        # 2. Retrieve relevant context (may find related classes)
        assembled = await self.assembler.assemble(
            query=f"class {cls.name} complexity methods",
            scope_key=scope_key,
            budget_tokens=1500,
        )

        # 3. Load versioned prompt from YAML + build request
        cfg = _registry.load("code_analysis", "v1")
        request = _registry.build_request(
            cfg, "analyze_class",
            include_tools=False,   # per-class analysis: LLM returns JSON directly
            context=assembled.text,
            class_name=cls.name,
        )

        # 4. Single-shot LLM call (no tool loop needed for per-class JSON report)
        response = await self.llm.complete(request)

        # 5. Parse JSON response — strip markdown fences if present
        content = response.content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1]) if len(lines) > 2 else content

        try:
            report = json.loads(content)
        except json.JSONDecodeError:
            report = {
                "class": cls.name,
                "error": "LLM returned non-JSON",
                "raw": response.content[:200],
            }

        out_tokens = response.usage.output_tokens if response.usage else 60
        return AgentResult(
            task_id=task.task_id,
            output=json.dumps(report),
            cost=Cost(
                input_tokens=assembled.token_count + 80,
                output_tokens=out_tokens,
                usd=round((assembled.token_count + 80 + out_tokens) * 0.00000015, 8),
                provider="openai",
                model=cfg.model,
            ),
        )


# ---------------------------------------------------------------------------
# Orchestrator — runs N ClassAnalysisAgents in parallel
# ---------------------------------------------------------------------------

@dataclass
class CodebaseAnalysisOrchestrator:
    """
    Phase ingestion + parallel multi-agent analysis.

    Flow:
      1. Ingest ClassInfo list into GraphBackbone (shared knowledge)
      2. Spawn one ClassAnalysisAgent per class, register in AgentPool
      3. Run all agents concurrently via AgentPool.fan_out (bounded by max_concurrency)
      4. Aggregate results into CodebaseReport
    """
    shared_backbone: GraphBackbone = field(default_factory=GraphBackbone)
    max_concurrency: int = 8

    async def analyse(
        self,
        classes: list[ClassInfo],
        base_context: ExecutionContext,
        agent_factory: AgentFactory,
    ) -> CodebaseReport:
        """Run all class agents in parallel via AgentPool.fan_out."""
        start_time = time.monotonic()

        # Build one agent per class and register in pool
        pool = AgentPool(max_concurrency=self.max_concurrency)
        for cls in classes:
            agent = agent_factory.build(cls, shared_backbone=self.shared_backbone)
            pool.register(agent)

        # One task per class — fan_out routes task[i] → agent[i] (round_robin)
        tasks = [
            Task(task_id=f"cls-{cls.name}", payload={"class": cls.name})
            for cls in classes
        ]

        # collect mode: 1 worker failure doesn't cancel others
        agent_results = await pool.fan_out(tasks, base_context, on_error="collect")

        results: list[dict[str, Any]] = []
        errors: list[str] = []
        for cls, ar in zip(classes, agent_results, strict=True):
            if ar.success and ar.output is not None:
                try:
                    results.append(json.loads(ar.output))
                except (json.JSONDecodeError, TypeError):
                    errors.append(f"{cls.name}: failed to parse output")
            else:
                errors.append(f"{cls.name}: {ar.metadata.get('error', 'unknown error')}")

        elapsed = time.monotonic() - start_time
        return CodebaseReport(
            class_reports=results,
            errors=errors,
            total_classes=len(classes),
            elapsed_seconds=elapsed,
        )


# ---------------------------------------------------------------------------
# CodebaseReport
# ---------------------------------------------------------------------------

@dataclass
class CodebaseReport:
    class_reports: list[dict[str, Any]]
    errors: list[str]
    total_classes: int
    elapsed_seconds: float

    def high_priority(self) -> list[dict[str, Any]]:
        return [r for r in self.class_reports if r.get("refactor_priority") == "HIGH"]

    def by_complexity(self) -> list[dict[str, Any]]:
        order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        return sorted(
            self.class_reports,
            key=lambda r: (order.get(r.get("complexity", "LOW"), 2), -r.get("complexity_score", 0)),
        )

    def print_summary(self) -> None:
        print(f"\n  Analysed : {len(self.class_reports)}/{self.total_classes} classes")
        print(f"  Errors   : {len(self.errors)}")
        print(f"  Time     : {self.elapsed_seconds:.2f}s (parallel, up to {self.total_classes} agents)")

        high = self.high_priority()
        print(f"\n  🔴 HIGH priority refactors ({len(high)}):")
        for r in high[:5]:
            issues = "; ".join(r.get("issues", []))
            print(f"    • {r['class']} [{r.get('module', '?')}] — {issues}")

        ranked = self.by_complexity()[:5]
        print("\n  📊 Top 5 most complex classes:")
        for r in ranked:
            score = r.get("complexity_score", "?")
            methods = r.get("method_count", "?")
            lines = r.get("lines", "?")
            print(f"    • {r['class']}: score={score}, {methods} methods, {lines}L")

        if self.errors:
            print("\n  ⚠️  Errors:")
            for e in self.errors:
                print(f"    • {e}")


# ---------------------------------------------------------------------------
# AgentFactory — shared OpenAI provider or per-class fake
# ---------------------------------------------------------------------------

@dataclass
class AgentFactory:
    """Builds one ClassAnalysisAgent per class.

    OpenAI mode  : shares one OpenAIProvider instance (stateless, safe to share)
    Demo mode    : builds a per-class FakeLLMProvider with deterministic analysis
    """
    _shared_llm: ILLMProvider | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            from ryuu.providers.adapters.openai import OpenAIProvider
            self._shared_llm = OpenAIProvider(api_key=api_key)  # type: ignore[assignment]

    def build(self, cls: ClassInfo, shared_backbone: GraphBackbone) -> ClassAnalysisAgent:
        from examples._utils import silent_tracer
        from ryuu.observability.audit import AuditLogger
        from ryuu.observability.cost import CostPolicy, CostTracker
        from ryuu.observability.rate_limit import RateLimiter, RatePolicy

        # OpenAI: share one instance (stateless HTTP calls)
        # Demo: per-class fake so each agent gets its own deterministic response
        _llm_impl = (
            self._shared_llm
            if self._shared_llm is not None
            else _build_class_llm(cls)
        )
        llm: ILLMProvider = _llm_impl  # type: ignore[assignment]

        return ClassAnalysisAgent(
            agent_id=f"analyst-{cls.name}",
            llm=llm,
            assembler=ContextAssembler(shared_backbone),
            cls_info=cls,
            cost_tracker=CostTracker(CostPolicy()),
            tracer=silent_tracer(),
            audit_logger=AuditLogger(),
            rate_limiter=RateLimiter(RatePolicy()),
        )
