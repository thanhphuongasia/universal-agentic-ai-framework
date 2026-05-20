"""Cost tracking and budget enforcement per scope.

Phase 0 uses in-memory storage. Phase 5 will add persistent backends
(Postgres / Redis) via the ICostStore Protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from uaaf_workflow.errors import BudgetExceededError

# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Cost:
    """Immutable record of LLM call cost."""

    input_tokens: int
    output_tokens: int
    usd: float
    provider: str
    model: str

    @classmethod
    def zero(cls, provider: str = "unknown", model: str = "unknown") -> Cost:
        return cls(input_tokens=0, output_tokens=0, usd=0.0, provider=provider, model=model)


@dataclass(frozen=True)
class CostPolicy:
    """Budget caps per scope dimension.  None means uncapped."""

    per_user_per_day_usd: float | None = None
    per_domain_per_month_usd: float | None = None
    global_per_hour_usd: float | None = None


@dataclass
class UsageSnapshot:
    scope_key: str
    total_usd: float
    total_input_tokens: int
    total_output_tokens: int
    call_count: int


# ---------------------------------------------------------------------------
# Storage protocol + in-memory implementation
# ---------------------------------------------------------------------------


@runtime_checkable
class ICostStore(Protocol):
    def record(self, scope_key: str, cost: Cost) -> None: ...
    def get(self, scope_key: str) -> UsageSnapshot: ...
    def reset(self, scope_key: str) -> None: ...


class InMemoryCostStore:
    def __init__(self) -> None:
        self._data: dict[str, UsageSnapshot] = {}

    def record(self, scope_key: str, cost: Cost) -> None:
        prev = self._data.get(scope_key) or UsageSnapshot(scope_key, 0.0, 0, 0, 0)
        self._data[scope_key] = UsageSnapshot(
            scope_key=scope_key,
            total_usd=prev.total_usd + cost.usd,
            total_input_tokens=prev.total_input_tokens + cost.input_tokens,
            total_output_tokens=prev.total_output_tokens + cost.output_tokens,
            call_count=prev.call_count + 1,
        )

    def get(self, scope_key: str) -> UsageSnapshot:
        return self._data.get(scope_key) or UsageSnapshot(scope_key, 0.0, 0, 0, 0)

    def reset(self, scope_key: str) -> None:
        self._data.pop(scope_key, None)


# ---------------------------------------------------------------------------
# CostTracker
# ---------------------------------------------------------------------------


@dataclass
class CostTracker:
    """Track and enforce LLM cost budgets per scope.

    ``scope_key`` is a plain string (e.g. ``"domain:user_id:session_id"``).
    Callers derive it from ``ContextScope.scope_key``.
    """

    policy: CostPolicy = field(default_factory=CostPolicy)
    store: ICostStore = field(default_factory=InMemoryCostStore)

    def record(self, scope_key: str, cost: Cost) -> None:
        """Accumulate *cost* under *scope_key*."""
        self.store.record(scope_key, cost)

    def get_usage(self, scope_key: str) -> UsageSnapshot:
        return self.store.get(scope_key)

    def enforce(self, scope_key: str, estimated: Cost) -> None:
        """Raise ``BudgetExceededError`` if adding *estimated* would breach any cap.

        Call this *before* the LLM call to prevent overspend.
        """
        snapshot = self.store.get(scope_key)
        projected = snapshot.total_usd + estimated.usd

        if (
            self.policy.per_user_per_day_usd is not None
            and projected > self.policy.per_user_per_day_usd
        ):
            raise BudgetExceededError(
                f"Scope {scope_key!r}: projected ${projected:.4f} exceeds "
                f"per-user-per-day cap ${self.policy.per_user_per_day_usd:.4f}"
            )

        if (
            self.policy.per_domain_per_month_usd is not None
            and projected > self.policy.per_domain_per_month_usd
        ):
            raise BudgetExceededError(
                f"Scope {scope_key!r}: projected ${projected:.4f} exceeds "
                f"per-domain-per-month cap ${self.policy.per_domain_per_month_usd:.4f}"
            )

        if (
            self.policy.global_per_hour_usd is not None
            and projected > self.policy.global_per_hour_usd
        ):
            raise BudgetExceededError(
                f"Scope {scope_key!r}: projected ${projected:.4f} exceeds "
                f"global-per-hour cap ${self.policy.global_per_hour_usd:.4f}"
            )

    def reset(self, scope_key: str) -> None:
        """Clear accumulated usage for *scope_key* (e.g. daily reset)."""
        self.store.reset(scope_key)
