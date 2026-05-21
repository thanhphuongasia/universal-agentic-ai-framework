"""RED tests for ryuu_observability.cost."""

from __future__ import annotations

import pytest


def test_cost_tracker_import() -> None:
    from ryuu_observability.cost import CostPolicy, CostTracker
    ct = CostTracker(policy=CostPolicy(per_user_per_day_usd=10.0))
    assert ct is not None


def test_cost_tracker_record_and_get() -> None:
    from ryuu_core.models import Cost
    from ryuu_observability.cost import CostTracker

    ct = CostTracker()
    cost = Cost(input_tokens=100, output_tokens=50, usd=0.01, provider="openai", model="gpt-4o")
    ct.record("user:alice", cost)
    snap = ct.get_usage("user:alice")
    assert snap.total_usd == pytest.approx(0.01)
    assert snap.call_count == 1


def test_cost_tracker_enforce_raises_on_breach() -> None:
    from ryuu_core.errors import BudgetExceededError
    from ryuu_core.models import Cost
    from ryuu_observability.cost import CostPolicy, CostTracker

    ct = CostTracker(policy=CostPolicy(per_user_per_day_usd=0.005))
    estimated = Cost(input_tokens=1000, output_tokens=500, usd=0.01, provider="openai", model="gpt-4o")
    with pytest.raises(BudgetExceededError):
        ct.enforce("user:alice", estimated)


def test_usage_snapshot_import() -> None:
    from ryuu_observability.cost import UsageSnapshot
    snap = UsageSnapshot(scope_key="k", total_usd=1.0, total_input_tokens=10, total_output_tokens=5, call_count=1)
    assert snap.total_usd == 1.0
