"""
Todo App — UAAF Example (refactored)
=====================================
Uses: OpenAI (real) + PromptRegistry (YAML versioning) + ToolRegistry (function calling)

Run:
    OPENAI_API_KEY=sk-... python -m examples.todo_app.main
    python -m examples.todo_app.main          # demo mode with FakeLLMProvider
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from examples._utils import silent_tracer
from examples.todo_app.agent import TodoAnalysisAgent, build_provider
from examples.todo_app.models import Status, build_mock_data
from examples.todo_app.tools import build_todo_registry
from uaaf.execution import PrintCallbacks
from uaaf.execution.agent import Task as AgentTask
from uaaf.observability.audit import AuditLogger
from uaaf.observability.cost import CostPolicy, CostTracker
from uaaf.observability.rate_limit import RateLimiter, RatePolicy
from uaaf.prompts.registry import PromptRegistry
from uaaf.runtime.context import ContextScope, ExecutionContext


def print_separator(title: str = "") -> None:
    width = 64
    if title:
        pad = (width - len(title) - 2) // 2
        print(f"\n{'─' * pad} {title} {'─' * pad}")
    else:
        print(f"\n{'─' * width}")


async def main() -> None:
    # ── Prompt registry info ────────────────────────────────────────────────
    prompts_root = Path(__file__).parent.parent.parent / "prompts"
    registry = PromptRegistry(prompts_root=prompts_root)
    cfg = registry.load("todo_app", "v1")

    print_separator("UAAF Todo App — OpenAI + PromptRegistry + Tools")
    print("\n  Prompt config : prompts/todo_app/v1.yaml")
    print(f"  Version       : {cfg.version}  |  Model: {cfg.model}  |  Temp: {cfg.temperature}")
    print(f"  Prompts       : {list(cfg.prompts)}")
    print(f"  Tools defined : {[t.name for t in cfg.tools]}")

    # ── Build mock data ─────────────────────────────────────────────────────
    goals, tasks = build_mock_data()
    print_separator("Portfolio")
    print(f"\n  {len(goals)} goals, {len(tasks)} tasks")
    for goal in goals:
        print(f"  {goal.summary()}")

    # ── Wire agent ──────────────────────────────────────────────────────────
    llm = build_provider()
    tool_registry = build_todo_registry(goals, tasks)

    agent = TodoAnalysisAgent(
        agent_id="todo-analyst",
        llm=llm,
        tool_registry=tool_registry,
        callbacks=PrintCallbacks(),
        cost_tracker=CostTracker(CostPolicy(
            per_user_per_day_usd=1.0,
            per_domain_per_month_usd=20.0,
            global_per_hour_usd=5.0,
        )),
        tracer=silent_tracer(),
        audit_logger=AuditLogger(),
        rate_limiter=RateLimiter(RatePolicy(rps=1.0, burst=10)),
    )

    scope = ContextScope(user_id="demo-user", session_id="todo-session-1", domain="todo")
    ctx = ExecutionContext(scope=scope, correlation_id="demo-001")

    # ── Ingest ─────────────────────────────────────────────────────────────
    print_separator("Ingestion → MemoryBackbone")
    await agent.ingest_goals(goals, scope_key=scope.session_id)
    print(f"  ✅ {len(goals) + len(tasks)} observations written")

    # ── Queries ─────────────────────────────────────────────────────────────
    queries = [
        ("Full Analysis",      "analyze",          "Analyze my goals and tasks. Show completion rates, effort accuracy, and blockers."),
        ("Priority Breakdown", "priority_breakdown","Give me a JSON breakdown of completed tasks by priority and effort per goal."),
        ("Next Sprint",        "next_sprint",       "What should I focus on next sprint to maximize goal completion?"),
    ]

    for label, prompt_name, query in queries:
        print_separator(f"{label}  [{prompt_name}]")
        print(f"  System prompt : prompts/todo_app/v1.yaml → prompts.{prompt_name}.system")
        print(f"  User          : {query}\n")

        result = await agent.execute(
            AgentTask(
                task_id=f"q-{prompt_name}",
                payload={"query": query, "prompt": prompt_name},
            ),
            ctx,
        )
        print(result.output)
        print(f"\n  💰 ${result.cost.usd:.6f} | in={result.cost.input_tokens} out={result.cost.output_tokens} | model={cfg.model}")

    # ── Tool demo (direct call, without LLM) ───────────────────────────────
    print_separator("Tool Calls — Direct Demo")
    print("  (Shows what the LLM would receive as tool results)\n")

    tool_demos: list[dict[str, Any]] = [
        {"id": "tc1", "function": {"name": "get_task_stats",    "arguments": {"goal_id": "g1"}}},
        {"id": "tc2", "function": {"name": "get_effort_analysis","arguments": {"goal_id": "all", "min_ratio": 1.1}}},
        {"id": "tc3", "function": {"name": "get_next_priorities","arguments": {"limit": 4}}},
    ]
    for demo in tool_demos:
        fn_name = demo["function"]["name"]
        fn_args = demo["function"]["arguments"]
        result_str = await tool_registry.run(demo)
        result_data = __import__("json").loads(result_str)
        print(f"  🔧 {fn_name}({fn_args})")
        # Pretty-print key parts
        import json
        print(f"     → {json.dumps(result_data, indent=6)[:400]}")
        print()

    # ── Summary stats ───────────────────────────────────────────────────────
    print_separator("Summary Stats")
    for goal in goals:
        completed = [t for t in goal.tasks if t.status == Status.COMPLETED]
        if not completed:
            continue
        avg_ratio = sum(t.effort_ratio for t in completed) / len(completed)
        print(f"\n  [{goal.goal_id.upper()}] {goal.name}")
        print(f"    Completion : {goal.completion_rate * 100:.0f}%")
        print(f"    Effort     : {goal.total_actual_hours:.1f}h / {goal.total_estimated_hours:.1f}h  (avg {avg_ratio:.2f}x)")

    print_separator()
    print("  Prompt versioning: bump to v2.yaml to iterate prompts without code changes")
    print("  Tool calling:      LLM chooses tools from YAML schema, Python executes them\n")


if __name__ == "__main__":
    asyncio.run(main())
