"""
Todo App — UAAF Example
========================
Demonstrates two equivalent dispatch paths:

  Mode A  direct       agent.execute(Task(...))           — caller picks prompt
  Mode B  handler      RequestHandler.handle(message)     — analyzer picks prompt

Both paths run the SAME 3 queries through the SAME agent class. The only
difference is who decides which prompt template + strategy to use.

Run:
    OPENAI_API_KEY=sk-... python -m examples.todo_app.main             # both modes
    python -m examples.todo_app.main direct                            # mode A only
    python -m examples.todo_app.main handler                           # mode B (rule analyzer)
    python -m examples.todo_app.main handler llm                       # mode B (LLM analyzer)
    python -m examples.todo_app.main                                   # demo (FakeLLM)

CLI: <mode> [analyzer]
  mode     : direct | handler | both       (default: both)
  analyzer : rule   | llm                  (default: rule, see ANALYZER_MODE)
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from examples.todo_app.agent import TodoAnalysisAgent, build_provider
from examples.todo_app.intent import TodoIntentAnalyzer, build_llm_analyzer
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
from uaaf.runtime.context import ContextScope, ExecutionContext
from uaaf.runtime.request_handler import RequestHandler

# ---------------------------------------------------------------------------
# Query presets — picked interactively at runtime (simple → complex)
# ---------------------------------------------------------------------------

# Tuple format: (label, complexity_hint, prompt_name, query)
#   - complexity_hint : LOW / MEDIUM / HIGH — what the analyzer would classify it as
#   - prompt_name     : used by Mode A (caller picks); ignored by Mode B (analyzer picks)
PRESETS: list[tuple[str, str, str, str]] = [
    ("Priority Breakdown", "LOW",    "priority_breakdown",
     "Give me a JSON breakdown of completed tasks by priority and effort per goal."),
    ("Full Analysis",      "MEDIUM", "analyze",
     "Analyze my goals and tasks. Show completion rates, effort accuracy, and blockers."),
    ("Next Sprint",        "HIGH",   "next_sprint",
     "What should I focus on next sprint to maximize goal completion?"),
]


def _select_queries() -> list[tuple[str, str, str]] | None:
    """Prompt user to pick preset(s), enter a custom query, or exit.

    Returns:
      list of (label, prompt_name, query) tuples — to run
      None — user chose Exit (or non-TTY second iteration)
    """
    if not sys.stdin.isatty():
        # Non-TTY first call: run all presets. Caller breaks loop after.
        return [(label, prompt, q) for label, _, prompt, q in PRESETS]

    print_separator("Choose a query")
    for i, (label, level, _, query) in enumerate(PRESETS, 1):
        snippet = query[:64] + ("…" if len(query) > 64 else "")
        print(f"  {i}. [{level:<6}] {label:<20}  {snippet}")
    custom_idx = len(PRESETS) + 1
    all_idx = len(PRESETS) + 2
    print(f"  {custom_idx}. Custom        — type your own query")
    print(f"  {all_idx}. Run all presets — show full demo")
    print("  0. Exit")

    while True:
        raw = input(f"\nEnter choice [0-{all_idx}]: ").strip()
        try:
            choice = int(raw)
        except ValueError:
            print("  ⚠️  Enter a number.")
            continue

        if choice == 0:
            return None
        if 1 <= choice <= len(PRESETS):
            label, _, prompt, q = PRESETS[choice - 1]
            return [(label, prompt, q)]
        if choice == custom_idx:
            text = input("  Your query: ").strip()
            if not text:
                print("  ⚠️  Empty query.")
                continue
            # Custom queries default to "analyze" prompt for Mode A
            return [("Custom", "analyze", text)]
        if choice == all_idx:
            return [(label, prompt, q) for label, _, prompt, q in PRESETS]
        print(f"  ⚠️  Choose between 0 and {all_idx}.")


# ---------------------------------------------------------------------------
# Analyzer switch — flip here OR via CLI: `python -m ... handler llm`
# ---------------------------------------------------------------------------

#  "rule" — TodoIntentAnalyzer  (keyword match, no LLM, fast, free)
#  "llm"  — LLMIntentAnalyzer   (real classification via LLM, costs tokens)
ANALYZER_MODE: str = "rule"


def _build_analyzer():
    """Build the IIntentAnalyzer used by RequestHandler — driven by ANALYZER_MODE."""
    if ANALYZER_MODE == "rule":
        return TodoIntentAnalyzer()
    if ANALYZER_MODE == "llm":
        return build_llm_analyzer()
    raise ValueError(f"Unknown ANALYZER_MODE {ANALYZER_MODE!r} — use 'rule' or 'llm'.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def print_separator(title: str = "") -> None:
    width = 64
    if title:
        pad = (width - len(title) - 2) // 2
        print(f"\n{'─' * pad} {title} {'─' * pad}")
    else:
        print(f"\n{'─' * width}")


def _build_agent(goals: list[Goal], tasks: list[Task]) -> TodoAnalysisAgent:
    """Build a fresh TodoAnalysisAgent — call once per mode for fair LLM-provider state."""
    from examples._utils import silent_tracer

    return TodoAnalysisAgent(
        agent_id="todo-analyst",
        llm=build_provider(),
        tool_registry=build_todo_registry(goals, tasks),
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


# ---------------------------------------------------------------------------
# Mode A — direct agent.execute()
# ---------------------------------------------------------------------------

async def run_with_direct_execute(
    agent: TodoAnalysisAgent,
    ctx: ExecutionContext,
    queries: list[tuple[str, str, str]],
) -> None:
    """Caller picks prompt_name explicitly + dispatches to agent directly.

    Bypasses cognitive routing — ctx.strategy_id stays None.
    """
    print_separator("Mode A — direct agent.execute()")

    for label, prompt_name, query in queries:
        print_separator(f"{label}  [{prompt_name}]")
        print(f"  User : {query}\n")

        result = await agent.execute(
            AgentTask(
                task_id=f"q-{prompt_name}",
                payload={"query": query, "prompt": prompt_name},
            ),
            ctx,
        )
        print(result.output)
        print(
            f"\n  💰 ${result.cost.usd:.6f} | in={result.cost.input_tokens}"
            f" out={result.cost.output_tokens} | strategy_id={ctx.strategy_id}"
        )


# ---------------------------------------------------------------------------
# Mode B — RequestHandler.handle()
# ---------------------------------------------------------------------------

async def run_with_request_handler(
    agent: TodoAnalysisAgent,
    ctx: ExecutionContext,
    queries: list[tuple[str, str, str]],
) -> None:
    """Analyzer classifies intent → selector picks strategy → strategy dispatches.

    Wiring:
      message
        → TodoIntentAnalyzer    classify: type / complexity / prompt_name
        → StrategySelector      pick strategy
        → ctx_routed            stamp strategy_id on immutable copy
        → TodoDirectStrategy    intent → Task payload, dispatch via pool
        → AgentPool.dispatch    route to registered agent
        → CognitiveResult       content + strategy_id (routing proof)
    """
    print_separator(f"Mode B — RequestHandler.handle()  [analyzer={ANALYZER_MODE}]")

    pool = AgentPool()
    pool.register(agent)
    analyzer = _build_analyzer()
    handler = RequestHandler(
        analyzer=analyzer,
        selector=StrategySelector([TodoDirectStrategy()]),
        pool=pool,
        verifier=FakeVerifier(),
    )

    for label, _, query in queries:  # prompt_name ignored — analyzer picks
        intent = await analyzer.analyze(query, ctx.scope.scope_key)
        print_separator(f"{label}  [{intent.entities['prompt_name']}]")
        print(f"  User       : {query}")
        print(f"  ├ type     : {intent.intent_type}")
        print(f"  ├ prompt   : {intent.entities['prompt_name']}  ← auto-selected")
        print(f"  ├ complexity: {intent.complexity.name}")
        print(f"  └ strategy : {intent.suggested_strategy}\n")

        result = await handler.handle(query, ctx)
        print(result.content)
        print(f"\n  strategy_id : '{result.strategy_id}'  ← routing proof")


# ---------------------------------------------------------------------------
# Display helpers (mode-independent)
# ---------------------------------------------------------------------------

def _print_portfolio(goals: list[Goal], tasks: list[Task]) -> None:
    print_separator("Portfolio")
    print(f"\n  {len(goals)} goals, {len(tasks)} tasks")
    for goal in goals:
        print(f"  {goal.summary()}")


async def _run_tool_demos(goals: list[Goal], tasks: list[Task]) -> None:
    print_separator("Tool Calls — Direct Demo")
    print("  (Shows what the LLM would receive as tool results)\n")

    tool_registry = build_todo_registry(goals, tasks)
    demos: list[dict[str, Any]] = [
        {"id": "tc1", "function": {"name": "get_task_stats",     "arguments": {"goal_id": "g1"}}},
        {"id": "tc2", "function": {"name": "get_effort_analysis","arguments": {"goal_id": "all", "min_ratio": 1.1}}},
        {"id": "tc3", "function": {"name": "get_next_priorities","arguments": {"limit": 4}}},
    ]
    for demo in demos:
        fn_name = demo["function"]["name"]
        fn_args = demo["function"]["arguments"]
        result_str = await tool_registry.run(demo)
        result_data = json.loads(result_str)
        print(f"  🔧 {fn_name}({fn_args})")
        print(f"     → {json.dumps(result_data, indent=6)[:400]}\n")


def _print_summary_stats(goals: list[Goal]) -> None:
    print_separator("Summary Stats")
    for goal in goals:
        completed = [t for t in goal.tasks if t.status == Status.COMPLETED]
        if not completed:
            continue
        avg_ratio = sum(t.effort_ratio for t in completed) / len(completed)
        print(f"\n  [{goal.goal_id.upper()}] {goal.name}")
        print(f"    Completion : {goal.completion_rate * 100:.0f}%")
        print(
            f"    Effort     : {goal.total_actual_hours:.1f}h /"
            f" {goal.total_estimated_hours:.1f}h  (avg {avg_ratio:.2f}x)"
        )


def _print_comparison_table() -> None:
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

# Map mode flag → run function. Add new modes here without touching main().
MODES = {
    #"direct":  run_with_direct_execute,
    "handler": run_with_request_handler,
}


async def main(mode: str = "both") -> None:
    if mode not in {*MODES, "both"}:
        raise SystemExit(f"Unknown mode {mode!r}. Use one of: direct, handler, both")

    print_separator("UAAF Todo App")
    print(f"\n  Mode: {mode}")

    goals, tasks = build_mock_data()
    _print_portfolio(goals, tasks)

    scope = ContextScope(user_id="demo-user", session_id="todo-session-1", domain="todo")
    ctx = ExecutionContext(scope=scope, correlation_id="demo-001")

    selected = list(MODES.items()) if mode == "both" else [(mode, MODES[mode])]

    # Build agents + ingest ONCE — reused across all loop iterations
    mode_agents: dict[str, TodoAnalysisAgent] = {}
    for mode_name, _ in selected:
        agent = _build_agent(goals, tasks)
        print_separator(f"Ingestion → MemoryBackbone  [{mode_name}]")
        await agent.ingest_goals(goals, scope_key=scope.session_id)
        print(f"  ✅ {len(goals) + len(tasks)} observations written")
        mode_agents[mode_name] = agent

    # ── Query loop — keep asking until user picks Exit ──────────────────────
    while True:
        queries = _select_queries()
        if queries is None:
            print("\n  👋 Bye!")
            break

        for mode_name, run_fn in selected:
            await run_fn(mode_agents[mode_name], ctx, queries)

        if mode == "both":
            _print_comparison_table()

        # Non-TTY: run once and exit (avoid CI infinite loop)
        if not sys.stdin.isatty():
            break

    await _run_tool_demos(goals, tasks)
    _print_summary_stats(goals)

    print_separator()
    print("  Swap modes via CLI arg: direct | handler | both (default)\n")


if __name__ == "__main__":
    # CLI: <mode> [analyzer]
    #   mode     : direct | handler | both       (default: both)
    #   analyzer : rule | llm                    (default: ANALYZER_MODE constant)
    cli_mode = sys.argv[1] if len(sys.argv) > 1 else "both"
    if len(sys.argv) > 2:
        if sys.argv[2] not in ("rule", "llm"):
            raise SystemExit(f"Unknown analyzer {sys.argv[2]!r}. Use 'rule' or 'llm'.")
        ANALYZER_MODE = sys.argv[2]
    asyncio.run(main(cli_mode))
