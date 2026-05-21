"""Todo App via Factory + facades — proves new API parity (Phase 10.x).

Same domain as `main.py` (class-based BaseAgent + custom strategies), but
expressed entirely through the new Factory + multi-agent facade API.

Compares with the original todo_app architecture to verify:
  - Mode C (pre-built ToolRegistry) works for DI tools
  - Factory `instructions=` covers basic system prompt use
  - `Router` facade replaces `StrategySelector` + `applicable()` for routing
  - `FanOut` facade replaces `TodoParallelStrategy` for per-goal fan-out
  - `Evaluator` facade replaces `TodoEvaluatorStrategy` for JSON refinement

Run:
    OPENAI_API_KEY=sk-... python -m examples.todo_app.factory_demo
    python -m examples.todo_app.factory_demo                            # FakeLLM demo
"""

from __future__ import annotations

import asyncio
import json
import os

from examples.todo_app.agent import build_provider
from examples.todo_app.models import build_mock_data
from examples.todo_app.tools import build_todo_registry
from ryuu import Agent, Evaluator, FanOut, Router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


SYSTEM_PROMPT = """You are a productivity analyst specializing in task management.
Analyze the goal/task portfolio and provide concrete, actionable insights.
Focus on completion rates, effort estimation accuracy, priority alignment, blockers.
"""


def _looks_like_json(text: str) -> bool:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.split("\n")
        if len(lines) > 2:
            stripped = "\n".join(lines[1:-1])
    try:
        json.loads(stripped)
        return True
    except (json.JSONDecodeError, ValueError):
        return False


def _json_verifier(output: str) -> tuple[bool, str]:
    """For Evaluator: JSON-shape check + feedback for refine."""
    if _looks_like_json(output):
        return True, ""
    return False, "Output must be valid JSON only. No prose, no markdown fences."


# ---------------------------------------------------------------------------
# Build agents — different prompts/behaviors per use case
# ---------------------------------------------------------------------------


def build_agents() -> dict[str, Agent]:
    """4 agents — one per intent type, sharing same tool registry."""
    goals, tasks = build_mock_data()
    tool_registry = build_todo_registry(goals, tasks)
    provider_factory = build_provider   # captures OPENAI_API_KEY decision

    common_kwargs = dict(
        model="gpt-4o-mini",
        tool_registry=tool_registry,    # Mode C — pre-built registry
        max_iterations=3,
        temperature=0.1,
        verbose=False,
    )

    # Helper: build Agent then swap in shared provider (so all share fake/real)
    def _agent(instructions: str) -> Agent:
        a = Agent(instructions=instructions, **common_kwargs)
        a._agent.llm = provider_factory()
        return a

    return {
        "analyze": _agent(
            SYSTEM_PROMPT
            + "\nProduce a free-form analysis with bullet points + rationale."
        ),
        "report": _agent(
            SYSTEM_PROMPT
            + "\nReturn ONLY valid JSON. Required keys: by_priority, "
            + "effort_by_goal, completion_rate_by_goal."
        ),
        "per_goal": _agent(
            SYSTEM_PROMPT
            + "\nFocus on ONE goal at a time. Report effort accuracy + blockers."
        ),
        "next_sprint": _agent(
            SYSTEM_PROMPT
            + "\nRecommend top 3-5 items for next sprint. Numbered list, with rationale."
        ),
    }


# ---------------------------------------------------------------------------
# Compose facades for each use case
# ---------------------------------------------------------------------------


async def run_use_case(label: str, query: str, agents: dict[str, Agent]) -> str:
    """Dispatch query to the right facade based on intent keywords."""
    print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  📋 {label}")
    print(f"  📝 Query: {query}")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # Use Case 1: JSON Report → Evaluator facade (auto-refine on bad shape)
    if "json" in query.lower() or "breakdown" in query.lower():
        evaluator = Evaluator(
            generator=agents["report"],
            verifier=_json_verifier,
            max_refines=2,
        )
        print("  🔄 Pattern: Evaluator (generate → verify JSON → refine)")
        output = await evaluator.run(query)
        valid = _looks_like_json(output)
        print(f"  ✅ JSON valid: {valid}")

    # Use Case 2: Per-goal Fan-out → FanOut facade with items=goal_ids
    elif "each goal" in query.lower() or "every goal" in query.lower() or "separately" in query.lower():
        fanout = FanOut(
            agent=agents["per_goal"],
            items=["g1", "g2", "g3"],
            template=f"{query} (focus only on goal {{item}})",
        )
        print("  🔀 Pattern: FanOut (3 subtasks per goal, parallel)")
        results = await fanout.run()
        output = "\n\n".join(
            f"━━ {gid.upper()} ━━\n{getattr(r, 'output', str(r))}"
            for gid, r in zip(["g1", "g2", "g3"], results, strict=True)
        )

    # Use Case 3 + 4: Free-form analysis / next sprint → Router by keyword
    else:
        router = Router(
            routes={
                "next_sprint": agents["next_sprint"],
                "analyze": agents["analyze"],
            },
            analyzer=lambda q: "next_sprint" if "sprint" in q.lower() else "analyze",
        )
        print("  🎯 Pattern: Router (keyword → analyze | next_sprint)")
        output = await router.run(query)

    preview = output[:300] + "..." if len(output) > 300 else output
    print(f"\n  📤 Output preview:\n{preview}")
    return output


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    has_key = bool(os.getenv("OPENAI_API_KEY"))
    print("=" * 72)
    print(f"  Todo App — Factory + Facades Demo (Phase 10.x parity)")
    print(f"  Provider mode: {'OpenAI (real)' if has_key else 'FakeLLM (demo)'}")
    print("=" * 72)

    agents = build_agents()

    queries = [
        ("Priority Breakdown (JSON)",
         "Give me a JSON breakdown of completed tasks by priority and effort per goal."),
        ("Per-Goal Effort (Fan-out)",
         "Analyze each goal separately and report effort accuracy."),
        ("Full Analysis (Direct)",
         "Analyze my goals and tasks. Show completion rates and blockers."),
        ("Next Sprint (Routed)",
         "What should I focus on next sprint to maximize completion?"),
    ]

    for label, query in queries:
        try:
            await run_use_case(label, query, agents)
        except Exception as exc:
            print(f"\n  ❌ {label} failed: {type(exc).__name__}: {exc}")

    print("\n" + "=" * 72)
    print("  ✅ Demo complete — Factory + facade API covers all 4 todo_app patterns")
    print("  Compare with examples/todo_app/main.py (class-based + custom strategies)")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())
