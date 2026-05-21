"""Per-call + per-run limit tests.

Phase 10 T2.6 — 4 cases. Expected RED until T5 implementation.

Limits: max_tokens (per LLM call), temperature (per LLM call),
max_iterations (ReAct loop).
"""

from __future__ import annotations

import pytest

from ryuu.factory import Agent


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")


def test_max_tokens_forwarded_to_internal_agent() -> None:
    """`max_tokens=1024` set on internal agent for request building."""
    agent = Agent(model="gpt-4o-mini", max_tokens=1024)
    assert getattr(agent._agent, "_max_tokens", None) == 1024  # type: ignore[attr-defined]


def test_temperature_default_0_7() -> None:
    """`temperature` default 0.7, forwarded."""
    agent = Agent(model="gpt-4o-mini")
    assert getattr(agent._agent, "_temperature", None) == 0.7  # type: ignore[attr-defined]


def test_max_iterations_default_5() -> None:
    """`max_iterations` default 5, forwarded to ReAct loop."""
    agent = Agent(model="gpt-4o-mini")
    assert getattr(agent._agent, "_max_iterations", None) == 5  # type: ignore[attr-defined]


def test_validation_negative_max_tokens_raises() -> None:
    """max_tokens <= 0 → ValueError."""
    with pytest.raises(ValueError, match="max_tokens"):
        Agent(model="gpt-4o-mini", max_tokens=-1)
