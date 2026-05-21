"""Tests for ryuu.observability.cost — T04."""

from __future__ import annotations

import pytest

from ryuu.observability.cost import (
    Cost,
    CostPolicy,
    CostTracker,
)
from ryuu_workflow.errors import BudgetExceededError


def _cost(usd: float, inp: int = 10, out: int = 5) -> Cost:
    return Cost(input_tokens=inp, output_tokens=out, usd=usd, provider="openai", model="gpt-4o-mini")


# ---------------------------------------------------------------------------
# Record and get_usage
# ---------------------------------------------------------------------------


def test_record_accumulates() -> None:
    tracker = CostTracker()
    tracker.record("scope1", _cost(0.01))
    tracker.record("scope1", _cost(0.02))
    snap = tracker.get_usage("scope1")
    assert abs(snap.total_usd - 0.03) < 1e-9
    assert snap.call_count == 2
    assert snap.total_input_tokens == 20
    assert snap.total_output_tokens == 10


def test_record_isolates_scopes() -> None:
    tracker = CostTracker()
    tracker.record("scopeA", _cost(0.10))
    tracker.record("scopeB", _cost(0.05))
    assert abs(tracker.get_usage("scopeA").total_usd - 0.10) < 1e-9
    assert abs(tracker.get_usage("scopeB").total_usd - 0.05) < 1e-9


def test_get_usage_returns_zero_for_unknown_scope() -> None:
    tracker = CostTracker()
    snap = tracker.get_usage("unknown")
    assert snap.total_usd == 0.0
    assert snap.call_count == 0


def test_reset_clears_scope() -> None:
    tracker = CostTracker()
    tracker.record("s", _cost(0.5))
    tracker.reset("s")
    assert tracker.get_usage("s").total_usd == 0.0


# ---------------------------------------------------------------------------
# enforce — budget enforcement
# ---------------------------------------------------------------------------


def test_enforce_passes_when_under_budget() -> None:
    policy = CostPolicy(per_user_per_day_usd=1.0)
    tracker = CostTracker(policy=policy)
    tracker.record("u", _cost(0.50))
    # Should NOT raise — 0.50 + 0.40 = 0.90 < 1.0
    tracker.enforce("u", _cost(0.40))


def test_enforce_raises_when_over_per_user_per_day() -> None:
    policy = CostPolicy(per_user_per_day_usd=1.0)
    tracker = CostTracker(policy=policy)
    tracker.record("u", _cost(0.80))
    with pytest.raises(BudgetExceededError):
        tracker.enforce("u", _cost(0.30))  # 0.80 + 0.30 = 1.10 > 1.0


def test_enforce_raises_when_over_domain_monthly() -> None:
    policy = CostPolicy(per_domain_per_month_usd=5.0)
    tracker = CostTracker(policy=policy)
    tracker.record("d", _cost(4.90))
    with pytest.raises(BudgetExceededError):
        tracker.enforce("d", _cost(0.20))  # 4.90 + 0.20 = 5.10 > 5.0


def test_enforce_raises_when_over_global_hourly() -> None:
    policy = CostPolicy(global_per_hour_usd=2.0)
    tracker = CostTracker(policy=policy)
    tracker.record("g", _cost(1.99))
    with pytest.raises(BudgetExceededError):
        tracker.enforce("g", _cost(0.02))  # 1.99 + 0.02 = 2.01 > 2.0


def test_enforce_no_policy_never_raises() -> None:
    tracker = CostTracker(policy=CostPolicy())
    tracker.record("x", _cost(9999.0))
    tracker.enforce("x", _cost(9999.0))  # no caps — should not raise


def test_enforce_at_exact_cap_passes() -> None:
    policy = CostPolicy(per_user_per_day_usd=1.0)
    tracker = CostTracker(policy=policy)
    tracker.record("u", _cost(0.50))
    # 0.50 + 0.50 = exactly 1.0 — should NOT raise (strict >, not >=)
    tracker.enforce("u", _cost(0.50))


# ---------------------------------------------------------------------------
# Multi-scope isolation edge cases
# ---------------------------------------------------------------------------


def test_multi_scope_isolation() -> None:
    policy = CostPolicy(per_user_per_day_usd=1.0)
    tracker = CostTracker(policy=policy)
    tracker.record("user1", _cost(0.90))
    tracker.record("user2", _cost(0.10))
    # user1 exceeds its budget
    with pytest.raises(BudgetExceededError):
        tracker.enforce("user1", _cost(0.20))
    # user2 is fine
    tracker.enforce("user2", _cost(0.80))  # 0.10 + 0.80 = 0.90 < 1.0


def test_cost_zero_classmethod() -> None:
    c = Cost.zero()
    assert c.usd == 0.0
    assert c.input_tokens == 0
    assert c.output_tokens == 0
