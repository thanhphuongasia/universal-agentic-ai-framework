"""Factory `Agent()` — basic construction + validation tests.

Phase 10 T2.2 — 4 cases. Expected RED until T5 implementation.
"""

from __future__ import annotations

import pytest

from ryuu.factory import Agent


def test_smoke_minimal_args() -> None:
    """Agent constructs with just `model`."""
    agent = Agent(model="gpt-4o-mini")
    assert agent.model == "gpt-4o-mini"


def test_default_field_values() -> None:
    """Unset fields use sensible defaults."""
    agent = Agent(model="gpt-4o-mini")
    assert agent.instructions == ""
    assert agent.tools == []
    assert agent.temperature == 0.7
    assert agent.max_iterations == 5
    assert agent.max_tokens is None
    assert agent.budget_usd is None
    assert agent.rate_limit_rps is None
    assert agent.audit is False
    assert agent.trace is False
    assert agent.verbose is False


def test_validation_budget_negative_raises() -> None:
    """budget_usd <= 0 → ValueError."""
    with pytest.raises(ValueError, match="budget_usd"):
        Agent(model="gpt-4o-mini", budget_usd=-1.0)


def test_validation_empty_model_raises() -> None:
    """Empty model string → ValueError."""
    with pytest.raises(ValueError, match="model"):
        Agent(model="")
