"""
FastAPI SSE server for the code_analysis example.
Exposes POST /chat — runs the 3-state pipeline and streams RYUUEvents.

Run:
    OPENAI_API_KEY=sk-... uvicorn examples.code_analysis.server:app --reload
    uvicorn examples.code_analysis.server:app --reload   # demo mode (FakeLLM)
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from examples.code_analysis.workflow import AnalyseState, IngestState, SummarizeState
from ryuu_workflow.context import ContextScope, ExecutionContext

app = FastAPI(title="RYUU Code Analysis — SSE Chat")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    sessionId: str = ""
    history: list[dict[str, Any]] = []


def _make_ctx() -> ExecutionContext:
    return ExecutionContext(
        scope=ContextScope(user_id="web-user", session_id="chat-1", domain="codebase"),
        correlation_id="ca-web-001",
    )


def _parse_target(message: str) -> Path | None:
    """Extract a directory path mentioned in the message, or None for the default."""
    for word in message.split():
        p = Path(word)
        if p.exists() and p.is_dir():
            return p
    return None


async def _stream_analysis(message: str) -> AsyncIterator[dict[str, Any]]:
    t0 = time.monotonic()
    ctx = _make_ctx()
    target = _parse_target(message)
    target_label = str(target) if target else "ryuu/ (default)"

    # ── intent + strategy ──────────────────────────────────────────────────
    yield {"type": "intent_classified", "intent_type": "code_analysis", "confidence": 0.97}
    yield {"type": "strategy_selected", "strategy": "WorkflowEngine(ingest → analyse → summarize)"}

    # ── phase 1: ingest ────────────────────────────────────────────────────
    yield {"type": "thought", "content": f"Ingesting Python files from {target_label}..."}
    tr1 = await IngestState().execute(str(target) if target else None, ctx)
    classes = tr1.output
    modules = len({c.module for c in classes})
    yield {"type": "thought", "content": f"Extracted {len(classes)} classes across {modules} modules."}

    # ── phase 2: analyse ───────────────────────────────────────────────────
    yield {"type": "thought", "content": f"Running parallel agent analysis on {len(classes)} classes..."}
    tr2 = await AnalyseState().execute(classes, ctx)
    report = tr2.output

    # Stream top-10 class reports as tool events (highest complexity first)
    top = sorted(report.class_reports, key=lambda r: r.get("complexity_score", 0), reverse=True)[:10]
    per_class_ms = int(report.elapsed_seconds * 1000 / max(len(classes), 1))
    for r in top:
        yield {
            "type": "tool_call",
            "tool": "analyse_class",
            "args": {"class": r["class"], "module": r.get("module", "?")},
        }
        await asyncio.sleep(0.04)
        yield {
            "type": "tool_result",
            "tool": "analyse_class",
            "result": {
                "complexity": r.get("complexity"),
                "score": r.get("complexity_score"),
                "issues": r.get("issues", []),
                "suggestion": r.get("suggestion"),
            },
            "duration_ms": per_class_ms,
        }

    high_count = len(report.high_priority())
    yield {
        "type": "thought",
        "content": (
            f"Analysis complete — {report.total_classes} classes, "
            f"{high_count} high-priority refactor(s) found in {report.elapsed_seconds:.1f}s."
        ),
    }

    # ── phase 3: summarize ─────────────────────────────────────────────────
    yield {"type": "thought", "content": "Generating LLM codebase summary..."}
    tr3 = await SummarizeState().execute(report, ctx)
    summary: str = tr3.output

    # Stream summary word-by-word for a streaming effect
    words = summary.split(" ")
    for i, word in enumerate(words):
        yield {"type": "text_delta", "content": word if i == 0 else " " + word}
        if i % 10 == 9:
            await asyncio.sleep(0.015)

    # ── structured: complexity breakdown ───────────────────────────────────
    complexity_dist: dict[str, int] = {}
    for r in report.class_reports:
        key = r.get("complexity", "LOW")
        complexity_dist[key] = complexity_dist.get(key, 0) + 1

    has_doc = sum(1 for r in report.class_reports if r.get("has_docstring"))
    doc_pct = round(has_doc / len(report.class_reports) * 100, 1) if report.class_reports else 0.0

    yield {
        "type": "structured",
        "renderer": "code_analysis_summary",
        "data": {
            "total_classes": report.total_classes,
            "complexity_distribution": complexity_dist,
            "docstring_coverage_pct": doc_pct,
            "high_priority_refactors": report.high_priority()[:5],
        },
    }

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    yield {"type": "done", "cost_usd": 0.0, "duration_ms": elapsed_ms, "tokens_used": 0}


@app.post("/chat")
async def chat(req: ChatRequest) -> EventSourceResponse:
    async def generate():
        try:
            async for event in _stream_analysis(req.message):
                yield {"event": event["type"], "data": json.dumps(event)}
        except Exception as exc:
            yield {
                "event": "error",
                "data": json.dumps({"type": "error", "code": "INTERNAL_ERROR", "message": str(exc)}),
            }

    return EventSourceResponse(generate())
