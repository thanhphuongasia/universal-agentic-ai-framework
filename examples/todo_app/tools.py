"""
Tool handlers for TodoAnalysisAgent.

Architecture:
  YAML (prompts/todo_app/v1.yaml)  ← schema the LLM sees
  tools.py                          ← Python callables that do the real work
  TodoToolRegistry                  ← wires name → handler, runs tool_call loop
"""

from __future__ import annotations

from typing import Any

from examples.todo_app.models import Goal, Priority, Status, Task
from ryuu_execution import ToolRegistry

# ---------------------------------------------------------------------------
# Handler implementations
# ---------------------------------------------------------------------------

def build_todo_registry(goals: list[Goal], tasks: list[Task]) -> ToolRegistry:
    """Wire all tool handlers with access to the loaded goals/tasks."""
    registry = ToolRegistry()
    goal_map = {g.goal_id: g for g in goals}

    # ── get_task_stats ─────────────────────────────────────────────────────

    async def get_task_stats(goal_id: str, status_filter: str = "all") -> dict[str, Any]:
        target_tasks: list[Task]
        if goal_id == "all":
            target_tasks = list(tasks)
        elif goal_id in goal_map:
            target_tasks = goal_map[goal_id].tasks
        else:
            return {"error": f"Unknown goal_id: {goal_id}"}

        if status_filter != "all":
            target_tasks = [t for t in target_tasks if t.status == status_filter]

        counts: dict[str, int] = {s: 0 for s in ["completed", "in_progress", "pending", "cancelled"]}
        for t in target_tasks:
            counts[t.status] = counts.get(t.status, 0) + 1

        total = len(target_tasks)
        return {
            "goal_id": goal_id,
            "status_filter": status_filter,
            "total": total,
            **counts,
            "completion_rate_pct": round(counts["completed"] / total * 100, 1) if total else 0.0,
        }

    registry.register("get_task_stats", get_task_stats)

    # ── get_effort_analysis ────────────────────────────────────────────────

    async def get_effort_analysis(goal_id: str, min_ratio: float = 0.0) -> dict[str, Any]:
        if goal_id == "all":
            completed = [t for t in tasks if t.status == Status.COMPLETED]
        elif goal_id in goal_map:
            completed = [t for t in goal_map[goal_id].tasks if t.status == Status.COMPLETED]
        else:
            return {"error": f"Unknown goal_id: {goal_id}"}

        filtered = [t for t in completed if t.effort_ratio >= min_ratio]
        rows = [
            {
                "task_id": t.task_id,
                "title": t.title,
                "goal_id": t.goal_id,
                "estimated_h": t.effort_hours,
                "actual_h": t.actual_hours,
                "ratio": round(t.effort_ratio, 2),
                "status": "over" if t.effort_ratio > 1.1 else "under" if t.effort_ratio < 0.9 else "on_target",
            }
            for t in sorted(filtered, key=lambda t: t.effort_ratio, reverse=True)
        ]
        total_est = sum(t.effort_hours for t in filtered)
        total_act = sum(t.actual_hours for t in filtered)
        return {
            "goal_id": goal_id,
            "min_ratio_filter": min_ratio,
            "task_count": len(rows),
            "total_estimated_h": round(total_est, 1),
            "total_actual_h": round(total_act, 1),
            "overall_ratio": round(total_act / total_est, 2) if total_est else 0.0,
            "tasks": rows,
        }

    registry.register("get_effort_analysis", get_effort_analysis)

    # ── get_next_priorities ────────────────────────────────────────────────

    priority_order = {Priority.CRITICAL: 0, Priority.HIGH: 1, Priority.MEDIUM: 2, Priority.LOW: 3}
    goal_priority_order = {g.goal_id: priority_order[g.priority] for g in goals}

    async def get_next_priorities(limit: int = 5, goal_filter: str | None = None) -> dict[str, Any]:
        actionable = [
            t for t in tasks
            if t.status in (Status.PENDING, Status.IN_PROGRESS)
            and (goal_filter is None or t.goal_id == goal_filter)
        ]
        sorted_tasks = sorted(
            actionable,
            key=lambda t: (
                goal_priority_order.get(t.goal_id, 99),
                priority_order.get(t.priority, 99),
            ),
        )
        return {
            "limit": limit,
            "goal_filter": goal_filter,
            "tasks": [
                {
                    "task_id": t.task_id,
                    "title": t.title,
                    "goal_id": t.goal_id,
                    "goal_priority": goal_map[t.goal_id].priority if t.goal_id in goal_map else "?",
                    "task_priority": t.priority,
                    "status": t.status,
                    "estimated_h": t.effort_hours,
                    "due_date": str(t.due_date) if t.due_date else None,
                }
                for t in sorted_tasks[:limit]
            ],
        }

    registry.register("get_next_priorities", get_next_priorities)
    return registry
