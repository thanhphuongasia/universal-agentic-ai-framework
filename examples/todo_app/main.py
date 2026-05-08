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

from examples.todo_app.agent import TodoAnalysisAgent, build_provider
from examples.todo_app.intent import TodoIntentAnalyzer
from examples.todo_app.models import Goal, Status, Task, build_mock_data
from examples.todo_app.strategies import TodoDirectStrategy
from examples.todo_app.tools import build_todo_registry
from uaaf._testing.fakes import FakeVerifier
from uaaf.execution import PrintCallbacks
from uaaf.execution.agent import Task as AgentTask
from uaaf.execution.pool import AgentPool
from uaaf.intent.selector import StrategySelector
from uaaf.observability.audit import AuditLogger
from uaaf.observability.cost import CostPolicy, CostTracker
from uaaf.observability.rate_limit import RateLimiter, RatePolicy
from uaaf.prompts.registry import PromptRegistry
from uaaf.runtime.context import ContextScope, ExecutionContext
from uaaf.runtime.request_handler import RequestHandler


def print_separator(title: str = "") -> None:
    width = 64
    if title:
        pad = (width - len(title) - 2) // 2
        print(f"\n{'─' * pad} {title} {'─' * pad}")
    else:
        print(f"\n{'─' * width}")


def _build_agent(
    goals: list[Goal],
    tasks: list[Task],
    session_id: str,
) -> TodoAnalysisAgent:
    """Build a fresh TodoAnalysisAgent with ingested data — reusable for both paths."""
    from examples._utils import silent_tracer

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
    return agent


async def run_with_request_handler(
    goals: list[Goal],
    tasks: list[Task],
    ctx: ExecutionContext,
) -> None:
    """Run the same 3 queries through RequestHandler — compare with direct agent.execute().

    Wiring:
      message
        → TodoIntentAnalyzer.analyze()     [classify: type / complexity / prompt_name]
        → StrategySelector.select()        [pick TodoDirectStrategy]
        → ctx_routed = replace(ctx, strategy_id="direct")
        → TodoDirectStrategy.execute()     [build Task payload, dispatch via pool]
        → AgentPool.dispatch(task, ctx_routed)
        → TodoAnalysisAgent.execute()      [cross-cutting + _react_loop]
        → CognitiveResult
    """
    print_separator("RequestHandler — Wiring")
    print("""
  message
    → TodoIntentAnalyzer     classify: intent_type / complexity / prompt_name
    → StrategySelector       pick strategy based on intent
    → ctx_routed             stamp strategy_id on immutable context copy
    → TodoDirectStrategy     translate intent → Task payload
    → AgentPool.dispatch     route to registered agent
    → TodoAnalysisAgent      same cross-cutting pipeline as direct call
    → CognitiveResult        content + strategy_id
    """)

    # Wire the RequestHandler
    agent = _build_agent(goals, tasks, ctx.scope.session_id)
    await agent.ingest_goals(goals, scope_key=ctx.scope.session_id)

    pool = AgentPool()
    pool.register(agent)

    analyzer = TodoIntentAnalyzer()
    handler = RequestHandler(
        analyzer=analyzer,
        selector=StrategySelector([TodoDirectStrategy()]),
        pool=pool,
        verifier=FakeVerifier(),
    )

    queries = [
        "Analyze my goals and tasks. Show completion rates, effort accuracy, and blockers.",
        "Give me a JSON breakdown of completed tasks by priority and effort per goal.",
        "What should I focus on next sprint to maximize goal completion?",
    ]

    for query in queries:
        # Show what the analyzer sees BEFORE dispatching
        intent = await analyzer.analyze(query, ctx.scope.scope_key)
        print_separator(f"Handler: {intent.intent_type.upper()}")
        print(f"  Query      : {query}")
        print(f"  ├ type     : {intent.intent_type}")
        print(f"  ├ prompt   : {intent.entities['prompt_name']}  ← auto-selected by analyzer")
        print(f"  ├ complexity: {intent.complexity.name}  (LOW→cheap, HIGH→standard model)")
        print(f"  └ strategy : {intent.suggested_strategy}\n")

        result = await handler.handle(query, ctx)

        print(f"\n  strategy_id on context : '{result.strategy_id}'  ← routing proof")
        print(f"  Output:\n  {result.content[:300]}")

    print_separator("Direct vs RequestHandler — Key Differences")
    print("""
  direct agent.execute()          RequestHandler.handle()
  ──────────────────────────────  ──────────────────────────────────────
  caller picks prompt_name        analyzer auto-selects prompt_name
  ctx.strategy_id = None          ctx.strategy_id = "direct"
  no intent classification        StructuredIntent: type + complexity
  no routing audit trail          strategy_id stamps every request
  hard to swap strategy later     swap strategy in StrategySelector only
    """)


async def main() -> None:
    # ── Prompt registry info ────────────────────────────────────────────────
    prompts_root = Path(__file__).parent / "prompts"
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

    scope = ContextScope(user_id="demo-user", session_id="todo-session-1", domain="todo")
    ctx = ExecutionContext(scope=scope, correlation_id="demo-001")

    # ── Wire agent ──────────────────────────────────────────────────────────
    agent = _build_agent(goals, tasks, scope.session_id)
    tool_registry = build_todo_registry(goals, tasks)

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

    # ── RequestHandler comparison ────────────────────────────────────────────
    await run_with_request_handler(goals, tasks, ctx)


if __name__ == "__main__":
    asyncio.run(main())
