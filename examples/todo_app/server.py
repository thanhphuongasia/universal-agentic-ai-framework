"""
FastAPI SSE server for the todo_app example.
Exposes:
  POST /chat       — streams UAAFEvents via SSE
  GET  /portfolio  — returns mock goals + tasks as JSON

Run:
    OPENAI_API_KEY=sk-... uvicorn examples.todo_app.server:app --reload
    uvicorn examples.todo_app.server:app --reload   # demo mode (FakeLLM)
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from examples._utils import silent_tracer
from examples.todo_app.agent import TodoAnalysisAgent, build_provider
from examples.todo_app.intent import TodoIntentAnalyzer
from examples.todo_app.models import build_mock_data
from examples.todo_app.strategies import (
    TodoDirectStrategy,
    TodoEvaluatorStrategy,
    TodoParallelStrategy,
    TodoReActStrategy,
)
from examples.todo_app.tools import build_todo_registry
from uaaf._testing.fakes import FakeVerifier
from uaaf.execution.pool import AgentPool
from uaaf.intent.selector import StrategySelector
from uaaf.observability.audit import AuditLogger
from uaaf.observability.cost import CostPolicy, CostTracker
from uaaf.observability.rate_limit import RateLimiter, RatePolicy
from uaaf_workflow.context import ContextScope, ExecutionContext
from uaaf.runtime.request_handler import RequestHandler

app = FastAPI(title="UAAF Todo App — SSE Chat")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

_GOALS, _TASKS = build_mock_data()


class ChatRequest(BaseModel):
    message: str
    sessionId: str = ""
    history: list[dict[str, Any]] = []


# ---------------------------------------------------------------------------
# QueueCallbacks — bridges ReActCallbacks hooks into an asyncio.Queue
# ---------------------------------------------------------------------------

class QueueCallbacks:
    """Captures _react_loop() events and puts them on a queue for SSE streaming."""

    def __init__(self, queue: "asyncio.Queue[dict[str, Any] | None]") -> None:
        self._q = queue

    async def on_thought(self, text: str) -> None:
        if text.strip():
            await self._q.put({"type": "thought", "content": text})

    async def on_action(self, tool_name: str, args: dict[str, Any]) -> None:
        await self._q.put({"type": "tool_call", "tool": tool_name, "args": args})

    async def on_observation(self, tool_name: str, result: str) -> None:
        try:
            parsed: Any = json.loads(result)
        except Exception:
            parsed = result
        await self._q.put({
            "type": "tool_result",
            "tool": tool_name,
            "result": parsed,
            "duration_ms": 0,
        })

    async def on_final(self, text: str) -> None:  # noqa: ARG002
        pass  # final content is streamed as text_delta after handle() returns


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx() -> ExecutionContext:
    return ExecutionContext(
        scope=ContextScope(user_id="web-user", session_id="todo-chat-1", domain="todo"),
        correlation_id="todo-web-001",
    )


def _build_agent(callbacks: QueueCallbacks) -> TodoAnalysisAgent:
    return TodoAnalysisAgent(
        agent_id="todo-analyst",
        llm=build_provider(),
        tool_registry=build_todo_registry(_GOALS, _TASKS),
        callbacks=callbacks,
        cost_tracker=CostTracker(CostPolicy(
            per_user_per_day_usd=1.0,
            per_domain_per_month_usd=20.0,
            global_per_hour_usd=5.0,
        )),
        tracer=silent_tracer(),
        audit_logger=AuditLogger(),
        rate_limiter=RateLimiter(RatePolicy(rps=1.0, burst=10)),
    )


# ---------------------------------------------------------------------------
# Streaming generator
# ---------------------------------------------------------------------------

async def _stream_todo(message: str) -> AsyncIterator[dict[str, Any]]:
    t0 = time.monotonic()
    ctx = _make_ctx()

    # ── 1. classify intent → emit early SSE events ───────────────────────────
    analyzer = TodoIntentAnalyzer()
    intent = await analyzer.analyze(message, ctx.scope.scope_key)
    yield {"type": "intent_classified", "intent_type": intent.intent_type, "confidence": 0.92}
    yield {"type": "strategy_selected", "strategy": intent.suggested_strategy or "direct"}

    # ── 2. build agent with queue-bridging callbacks ──────────────────────────
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    agent = _build_agent(QueueCallbacks(queue))

    pool = AgentPool()
    pool.register(agent)

    handler = RequestHandler(
        analyzer=analyzer,
        selector=StrategySelector([
            TodoParallelStrategy(),
            TodoEvaluatorStrategy(),
            TodoReActStrategy(),
            TodoDirectStrategy(),
        ]),
        pool=pool,
        verifier=FakeVerifier(),
    )

    # ── 3. run handler concurrently; drain callback events while it runs ──────
    async def run_handler() -> Any:
        result = await handler.handle(message, ctx)
        await queue.put(None)  # sentinel
        return result

    handle_task = asyncio.create_task(run_handler())

    while True:
        event = await queue.get()
        if event is None:
            break
        yield event

    result = await handle_task

    # ── 4. stream final answer word-by-word as text_delta ─────────────────────
    words = result.content.split(" ")
    for i, word in enumerate(words):
        yield {"type": "text_delta", "content": word if i == 0 else " " + word}
        if i % 10 == 9:
            await asyncio.sleep(0.015)

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    yield {"type": "done", "cost_usd": 0.0, "duration_ms": elapsed_ms, "tokens_used": 0}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.post("/chat")
async def chat(req: ChatRequest) -> EventSourceResponse:
    async def generate():
        try:
            async for event in _stream_todo(req.message):
                yield {"event": event["type"], "data": json.dumps(event)}
        except Exception as exc:
            yield {
                "event": "error",
                "data": json.dumps({"type": "error", "code": "INTERNAL_ERROR", "message": str(exc)}),
            }

    return EventSourceResponse(generate())


@app.get("/portfolio")
async def portfolio() -> dict[str, Any]:
    """Mock portfolio data for the frontend sidebar."""
    return {
        "goals": [
            {
                "goal_id": g.goal_id,
                "name": g.name,
                "priority": str(g.priority),
                "deadline": str(g.deadline),
                "completion_pct": round(g.completion_rate * 100, 1),
                "task_count": len(g.tasks),
                "actual_hours": g.total_actual_hours,
            }
            for g in _GOALS
        ],
        "tasks": [
            {
                "task_id": t.task_id,
                "title": t.title,
                "goal_id": t.goal_id,
                "priority": str(t.priority),
                "status": str(t.status),
                "effort_hours": t.effort_hours,
                "actual_hours": t.actual_hours,
            }
            for t in _TASKS
        ],
    }
