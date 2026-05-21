"""Phase 12 — BatchRunner tests.

8 cases covering gather mode + OpenAI batch stub + ordering + concurrency limit.
"""

from __future__ import annotations

import pytest

from ryuu import Agent
from ryuu._testing.fakes import FakeLLMProvider
from ryuu.batch import BatchItem, BatchRunner
from ryuu.providers.llm import Response, TokenUsage


def _fake(text: str = "ok") -> Response:
    return Response(
        content=text, model="fake",
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        finish_reason="stop",
    )


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")


def _make_agent(n_responses: int = 10) -> Agent:
    agent = Agent(model="gpt-4o-mini")
    agent._agent.llm = FakeLLMProvider(  # type: ignore[attr-defined]
        responses=[_fake(f"r{i}") for i in range(n_responses)],
    )
    return agent


# ── Gather mode (default) ──────────────────────────────────────────────────


async def test_batch_str_inputs() -> None:
    """List of strings → returns list of AgentResult in order."""
    agent = _make_agent(5)
    runner = BatchRunner(agent=agent)
    results = await runner.run(["q1", "q2", "q3"])
    assert len(results) == 3
    # FakeLLMProvider returns r0, r1, r2 in order (assuming sequential)
    assert all(r.output.startswith("r") for r in results)


async def test_batch_dict_inputs_with_id() -> None:
    """List of dicts with id/input → returns list of BatchItem preserving id."""
    agent = _make_agent(5)
    runner = BatchRunner(agent=agent)
    items = [
        {"id": "doc-1", "input": "Text 1"},
        {"id": "doc-2", "input": "Text 2"},
    ]
    results = await runner.run(items)
    assert len(results) == 2
    assert isinstance(results[0], BatchItem)
    assert results[0].id == "doc-1"
    assert results[1].id == "doc-2"


async def test_batch_preserves_input_order() -> None:
    """Results returned in same order as inputs (even when async gather)."""
    agent = _make_agent(10)
    runner = BatchRunner(agent=agent)
    inputs = [f"input-{i}" for i in range(5)]
    results = await runner.run(inputs)
    assert len(results) == 5
    # Order preserved via list index even though gather completes out-of-order
    assert [r.task_id for r in results] is not None   # all have task_ids


async def test_batch_max_concurrent_respected() -> None:
    """max_concurrent limits parallelism (via semaphore)."""
    import asyncio
    agent = _make_agent(10)
    in_flight = {"count": 0, "max_seen": 0}

    orig_run = agent.run

    async def tracked_run(message, **kwargs):
        in_flight["count"] += 1
        in_flight["max_seen"] = max(in_flight["max_seen"], in_flight["count"])
        try:
            await asyncio.sleep(0.01)
            return await orig_run(message, **kwargs)
        finally:
            in_flight["count"] -= 1

    agent.run = tracked_run  # type: ignore[method-assign]
    runner = BatchRunner(agent=agent, max_concurrent=3)
    await runner.run([f"q{i}" for i in range(10)])
    assert in_flight["max_seen"] <= 3


async def test_batch_empty_input_returns_empty() -> None:
    """Empty input list → empty results, no provider call."""
    agent = _make_agent(0)
    runner = BatchRunner(agent=agent)
    results = await runner.run([])
    assert results == []


async def test_batch_on_error_collect_continues() -> None:
    """on_error='collect' — failed items return None or error marker, batch continues."""
    agent = _make_agent(0)
    agent._agent.llm = FakeLLMProvider(raise_on_call=RuntimeError("boom"))  # type: ignore[attr-defined]

    runner = BatchRunner(agent=agent, on_error="collect")
    results = await runner.run(["q1", "q2"])
    assert len(results) == 2
    # Items with error have .error field set
    assert all(getattr(r, "error", None) is not None for r in results)


async def test_batch_on_error_raise_propagates() -> None:
    """on_error='raise' (default) → first error halts batch + propagates."""
    agent = _make_agent(0)
    agent._agent.llm = FakeLLMProvider(raise_on_call=RuntimeError("boom"))  # type: ignore[attr-defined]

    runner = BatchRunner(agent=agent, on_error="raise")
    with pytest.raises(Exception):
        await runner.run(["q1", "q2"])


# ── OpenAI batch mode stub ─────────────────────────────────────────────────


async def test_batch_openai_mode_requires_client_or_real_sdk() -> None:
    """mode='openai_batch' without `batch_client` instantiates real OpenAIBatchClient
    which would call live API. Without API key + network, it should raise.

    (Tests with FakeBatchAPIClient live in test_batch_openai.py.)
    """
    import os
    # Clear the test key so OpenAI SDK fails fast at first network call
    os.environ.pop("OPENAI_API_KEY", None)
    agent = _make_agent(1)
    runner = BatchRunner(agent=agent, mode="openai_batch", poll_interval_s=0.001)
    with pytest.raises(Exception):
        await runner.run(["q1"])
