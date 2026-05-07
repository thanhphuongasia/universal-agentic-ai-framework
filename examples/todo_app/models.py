"""Domain models for the Todo app example."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum


class Priority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Status(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    task_id: str
    title: str
    goal_id: str
    priority: Priority
    status: Status
    effort_hours: float          # estimated effort in hours
    actual_hours: float = 0.0   # actual time spent
    due_date: date | None = None
    completed_date: date | None = None
    tags: list[str] = field(default_factory=list)

    @property
    def effort_ratio(self) -> float:
        """actual / estimated — >1.0 means went over estimate."""
        if self.effort_hours == 0:
            return 0.0
        return self.actual_hours / self.effort_hours

    def summary(self) -> str:
        status_icon = {"completed": "✅", "in_progress": "🔄", "pending": "⏳", "cancelled": "❌"}[self.status]
        return (
            f"{status_icon} [{self.priority.upper()}] {self.title} "
            f"(goal={self.goal_id}, effort={self.actual_hours:.1f}h/{self.effort_hours:.1f}h)"
        )


@dataclass
class Goal:
    goal_id: str
    name: str
    description: str
    priority: Priority
    deadline: date | None = None
    tasks: list[Task] = field(default_factory=list)

    @property
    def completion_rate(self) -> float:
        if not self.tasks:
            return 0.0
        done = sum(1 for t in self.tasks if t.status == Status.COMPLETED)
        return done / len(self.tasks)

    @property
    def total_actual_hours(self) -> float:
        return sum(t.actual_hours for t in self.tasks if t.status == Status.COMPLETED)

    @property
    def total_estimated_hours(self) -> float:
        return sum(t.effort_hours for t in self.tasks if t.status == Status.COMPLETED)

    def summary(self) -> str:
        pct = self.completion_rate * 100
        return (
            f"[{self.priority.upper()}] {self.name}: "
            f"{pct:.0f}% done ({len(self.tasks)} tasks, "
            f"{self.total_actual_hours:.1f}h spent)"
        )


def build_mock_data() -> tuple[list[Goal], list[Task]]:
    """Return realistic mock goals + tasks for demo."""

    goals = [
        Goal(
            goal_id="g1",
            name="Launch MVP for BridgeH test",
            description="Ship v1.0 of the product to first 100 users",
            priority=Priority.CRITICAL,
            deadline=date(2026, 6, 1),
        ),
        Goal(
            goal_id="g2",
            name="Improve Code Quality",
            description="Reduce technical debt, increase test coverage to 90%",
            priority=Priority.HIGH,
            deadline=date(2026, 7, 1),
        ),
        Goal(
            goal_id="g3",
            name="Team Growth",
            description="Onboard 2 new engineers, set up documentation",
            priority=Priority.MEDIUM,
            deadline=date(2026, 8, 1),
        ),
    ]

    tasks = [
        # --- g1: Launch MVP ---
        Task("t01", "Design REST API schema",          "g1", Priority.CRITICAL, Status.COMPLETED,  4.0, 5.5,  date(2026, 4, 10), date(2026, 4, 11), ["backend", "api"]),
        Task("t02", "Implement auth endpoints",         "g1", Priority.CRITICAL, Status.COMPLETED,  8.0, 10.0, date(2026, 4, 15), date(2026, 4, 16), ["backend", "auth"]),
        Task("t03", "Build dashboard UI",               "g1", Priority.HIGH,     Status.COMPLETED,  12.0, 9.0, date(2026, 4, 25), date(2026, 4, 24), ["frontend"]),
        Task("t04", "Write integration tests",          "g1", Priority.HIGH,     Status.COMPLETED,   6.0, 7.5, date(2026, 4, 28), date(2026, 4, 29), ["testing"]),
        Task("t05", "Set up CI/CD pipeline",            "g1", Priority.MEDIUM,   Status.COMPLETED,   3.0, 3.0, date(2026, 5, 1),  date(2026, 4, 30), ["devops"]),
        Task("t06", "Deploy to production",             "g1", Priority.CRITICAL, Status.IN_PROGRESS, 2.0, 1.0, date(2026, 5, 10), None,              ["devops"]),
        Task("t07", "User onboarding emails",           "g1", Priority.MEDIUM,   Status.PENDING,     4.0, 0.0, date(2026, 5, 15), None,              ["marketing"]),

        # --- g2: Improve Code Quality ---
        Task("t08", "Add mypy to CI",                   "g2", Priority.HIGH,     Status.COMPLETED,   2.0, 1.5, date(2026, 4, 5),  date(2026, 4, 4),  ["devops", "quality"]),
        Task("t09", "Refactor auth module",             "g2", Priority.HIGH,     Status.COMPLETED,   6.0, 8.0, date(2026, 4, 20), date(2026, 4, 22), ["backend", "refactor"]),
        Task("t10", "Write unit tests for payments",    "g2", Priority.CRITICAL, Status.COMPLETED,   5.0, 5.0, date(2026, 4, 22), date(2026, 4, 21), ["testing", "payments"]),
        Task("t11", "Add ruff linter",                  "g2", Priority.LOW,      Status.COMPLETED,   1.0, 0.5, date(2026, 4, 8),  date(2026, 4, 7),  ["quality"]),
        Task("t12", "Migrate to async DB driver",       "g2", Priority.MEDIUM,   Status.IN_PROGRESS, 8.0, 3.0, date(2026, 5, 20), None,              ["backend", "performance"]),

        # --- g3: Team Growth ---
        Task("t13", "Write onboarding guide",           "g3", Priority.HIGH,     Status.COMPLETED,   4.0, 3.0, date(2026, 4, 12), date(2026, 4, 11), ["docs"]),
        Task("t14", "Record setup video",               "g3", Priority.MEDIUM,   Status.COMPLETED,   2.0, 3.5, date(2026, 4, 18), date(2026, 4, 19), ["docs"]),
        Task("t15", "testing candidate A",            "g3", Priority.HIGH,     Status.COMPLETED,   1.0, 1.0, date(2026, 4, 25), date(2026, 4, 25), ["hiring"]),
        Task("t16", "tesing candidate B",            "g3", Priority.HIGH,     Status.CANCELLED,   1.0, 0.0, date(2026, 4, 26), None,              ["hiring"]),
        Task("t17", "Set up dev environment docs",      "g3", Priority.LOW,      Status.PENDING,     3.0, 0.0, date(2026, 6, 1),  None,              ["docs"]),
    ]

    # Wire tasks into goals
    goal_map = {g.goal_id: g for g in goals}
    for task in tasks:
        goal_map[task.goal_id].tasks.append(task)

    return goals, tasks
