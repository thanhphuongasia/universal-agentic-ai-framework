"""
Tool handlers for CodebaseAnalysisOrchestrator.

Architecture:
  YAML (prompts/code_analysis/v1.yaml)  ← schema the LLM sees
  tools.py                               ← Python callables that do the real work
  build_code_registry()                  ← wires name → handler
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from examples.code_analysis.ingestion import ClassInfo

ToolHandler = Callable[..., Awaitable[Any]]


@dataclass
class ToolRegistry:
    """Maps tool name → async handler."""
    _handlers: dict[str, ToolHandler] = field(default_factory=dict)

    def register(self, name: str, handler: ToolHandler) -> None:
        self._handlers[name] = handler

    async def run(self, tool_call: dict[str, Any]) -> str:
        name = tool_call["function"]["name"]
        args = tool_call["function"]["arguments"]
        handler = self._handlers.get(name)
        if handler is None:
            return json.dumps({"error": f"Unknown tool: {name}"})
        result = await handler(**args)
        return json.dumps(result, default=str)

    async def run_all(self, tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results = []
        for tc in tool_calls:
            content = await self.run(tc)
            results.append({"tool_call_id": tc["id"], "content": content})
        return results


def build_code_registry(
    classes: list[ClassInfo],
    class_reports: list[dict[str, Any]],
) -> ToolRegistry:
    """Wire tool handlers with access to ingested classes + analysis reports."""
    registry = ToolRegistry()

    class_map = {c.name: c for c in classes}
    report_map = {r.get("class", ""): r for r in class_reports}

    # ── get_class_details ──────────────────────────────────────────────────

    async def get_class_details(class_name: str) -> dict[str, Any]:
        cls = class_map.get(class_name)
        if cls is None:
            available = list(class_map)[:10]
            return {"error": f"Class '{class_name}' not found.", "available_sample": available}
        return {
            "class": cls.name,
            "module": cls.module,
            "file": cls.file_path,
            "line_range": f"{cls.line_start}–{cls.line_end}",
            "total_lines": cls.line_count,
            "bases": cls.base_classes,
            "has_docstring": bool(cls.docstring),
            "docstring_preview": cls.docstring[:120] if cls.docstring else "",
            "complexity_score": cls.complexity_score,
            "methods": [
                {
                    "name": m.name,
                    "args": m.args,
                    "lines": m.line_count,
                    "async": m.is_async,
                    "property": m.is_property,
                    "has_docstring": bool(m.docstring),
                }
                for m in cls.methods
            ],
        }

    registry.register("get_class_details", get_class_details)

    # ── find_refactor_candidates ───────────────────────────────────────────

    async def find_refactor_candidates(
        min_complexity_score: int = 40,
        missing_docstring: bool = False,
        min_line_count: int = 0,
        priority: str = "all",
    ) -> dict[str, Any]:
        candidates = []
        for cls in classes:
            if cls.complexity_score < min_complexity_score:
                continue
            if cls.line_count < min_line_count:
                continue
            if missing_docstring and cls.docstring:
                continue

            report = report_map.get(cls.name, {})
            rp = report.get("refactor_priority", "LOW")
            if priority != "all" and rp != priority:
                continue

            candidates.append({
                "class": cls.name,
                "module": cls.module,
                "complexity_score": cls.complexity_score,
                "lines": cls.line_count,
                "has_docstring": bool(cls.docstring),
                "refactor_priority": rp,
                "issues": report.get("issues", []),
            })

        candidates.sort(key=lambda c: c["complexity_score"], reverse=True)
        return {
            "filters": {
                "min_complexity_score": min_complexity_score,
                "missing_docstring": missing_docstring,
                "min_line_count": min_line_count,
                "priority": priority,
            },
            "count": len(candidates),
            "candidates": candidates[:20],
        }

    registry.register("find_refactor_candidates", find_refactor_candidates)

    # ── get_module_summary ─────────────────────────────────────────────────

    async def get_module_summary(module_name: str) -> dict[str, Any]:
        module_classes = [c for c in classes if c.module == module_name]
        if not module_classes:
            modules = sorted({c.module for c in classes})
            return {"error": f"Module '{module_name}' not found.", "available_modules": modules}

        total_lines = sum(c.line_count for c in module_classes)
        total_async = sum(sum(1 for m in c.methods if m.is_async) for c in module_classes)
        avg_complexity = sum(c.complexity_score for c in module_classes) / len(module_classes)
        doc_count = sum(1 for c in module_classes if c.docstring)

        return {
            "module": module_name,
            "class_count": len(module_classes),
            "total_lines": total_lines,
            "avg_complexity_score": round(avg_complexity, 1),
            "async_method_count": total_async,
            "docstring_coverage_pct": round(doc_count / len(module_classes) * 100, 1),
            "classes": [
                {
                    "class": c.name,
                    "lines": c.line_count,
                    "complexity": c.complexity_score,
                    "methods": len(c.methods),
                    "has_docstring": bool(c.docstring),
                }
                for c in sorted(module_classes, key=lambda c: c.complexity_score, reverse=True)
            ],
        }

    registry.register("get_module_summary", get_module_summary)
    return registry
