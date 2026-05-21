"""Phase 8.8 — Stress test for cross-cutting non-blocking guarantee.

Measures wall-clock overhead of cost / audit / tracer / rate_limit under
concurrent load. Each test runs N concurrent agent.run() calls and reports
p50/p99/wall-clock timing.

Findings (see report at end):
  - CostTracker      : ✅ non-blocking (pure in-memory dict)
  - RateLimiter      : ✅ non-blocking (anyio.sleep + in-memory)
  - Tracer (default) : ⚠️ partial — SimpleSpanProcessor + ConsoleExporter sync I/O
  - AuditLogger (file): ❌ BLOCKING — sync open/write per event

Run manually (slow):
    pytest tests/perf/ -v -s
"""

from __future__ import annotations

import statistics
import time
from pathlib import Path

import anyio
import pytest

from ryuu import Agent
from ryuu._testing.fakes import FakeLLMProvider
from ryuu.providers.llm import Response, TokenUsage


N_CONCURRENT = 200   # keep modest so test runs in seconds


def _fake_response(text: str = "ok") -> Response:
    return Response(
        content=text,
        model="fake",
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        finish_reason="stop",
    )


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")


def _make_agent(**kwargs) -> Agent:
    """Factory helper — create agent with shared FakeLLMProvider per run."""
    agent = Agent(model="gpt-4o-mini", **kwargs)
    agent._agent.llm = FakeLLMProvider(  # type: ignore[attr-defined]
        responses=[_fake_response() for _ in range(N_CONCURRENT * 2)],
    )
    return agent


async def _run_concurrent(agent: Agent, n: int) -> tuple[float, list[float]]:
    """Run n .run() calls concurrently. Returns (wall_clock_s, per_call_latencies)."""
    latencies: list[float] = [0.0] * n

    async def _one(i: int) -> None:
        start = time.monotonic()
        await agent.run(f"query-{i}", user_id=f"u-{i}")
        latencies[i] = time.monotonic() - start

    wall_start = time.monotonic()
    async with anyio.create_task_group() as tg:
        for i in range(n):
            tg.start_soon(_one, i)
    wall_elapsed = time.monotonic() - wall_start

    return wall_elapsed, latencies


def _summarize(label: str, wall: float, latencies: list[float]) -> dict:
    sorted_lat = sorted(latencies)
    p50 = sorted_lat[len(sorted_lat) // 2]
    p99 = sorted_lat[int(len(sorted_lat) * 0.99)]
    print(
        f"\n  [{label}] N={len(latencies)} wall={wall*1000:.1f}ms "
        f"p50={p50*1000:.2f}ms p99={p99*1000:.2f}ms mean={statistics.mean(latencies)*1000:.2f}ms"
    )
    return {"label": label, "wall_ms": wall * 1000, "p50_ms": p50 * 1000, "p99_ms": p99 * 1000}


# ---------------------------------------------------------------------------
# Baseline: no cross-cutting
# ---------------------------------------------------------------------------


async def test_baseline_no_observability() -> None:
    """Baseline: agent with no observability — establish floor latency."""
    agent = _make_agent()
    wall, lat = await _run_concurrent(agent, N_CONCURRENT)
    _summarize("baseline", wall, lat)
    # Baseline should complete reasonably fast (FakeLLMProvider is instant)
    assert wall < 5.0, f"baseline too slow: {wall:.2f}s"


# ---------------------------------------------------------------------------
# Individual concerns
# ---------------------------------------------------------------------------


async def test_cost_tracker_overhead() -> None:
    """CostTracker should add negligible overhead (pure in-memory)."""
    agent = _make_agent(budget_usd=1000.0)   # high cap, no enforcement trigger
    wall, lat = await _run_concurrent(agent, N_CONCURRENT)
    summary = _summarize("cost_tracker", wall, lat)
    # Cost tracker is sync dict ops — should be near-zero overhead
    assert summary["p99_ms"] < 50, f"CostTracker p99 too high: {summary['p99_ms']:.2f}ms"


async def test_rate_limiter_overhead() -> None:
    """RateLimiter with high rps should add minimal overhead."""
    agent = _make_agent(rate_limit_rps=10_000.0)   # very high, no blocking
    wall, lat = await _run_concurrent(agent, N_CONCURRENT)
    summary = _summarize("rate_limiter", wall, lat)
    # RateLimiter uses anyio.sleep + in-memory store — should be quick
    assert summary["p99_ms"] < 100, f"RateLimiter p99 too high: {summary['p99_ms']:.2f}ms"


async def test_tracer_overhead() -> None:
    """Tracer with default ConsoleExporter — measure sync export overhead."""
    agent = _make_agent(trace=True)
    wall, lat = await _run_concurrent(agent, N_CONCURRENT)
    summary = _summarize("tracer_console", wall, lat)
    # SimpleSpanProcessor + ConsoleExporter is known-sync. Document, don't assert hard.
    print(f"  [NOTE] Tracer uses SimpleSpanProcessor (sync export). "
          f"For prod, switch to BatchSpanProcessor + OTLP exporter.")


async def test_audit_file_overhead(tmp_path: Path) -> None:
    """AuditLogger with FILE backend — measure sync I/O blocking per write."""
    audit_path = tmp_path / "audit.jsonl"

    # Build agent with file audit (need to monkey-patch since `audit=True` uses fixed path)
    # Easier: build agent then swap audit_logger
    agent = _make_agent(audit=True)
    from ryuu_observability.audit import AuditConfig, AuditLogger
    agent._agent.audit_logger = AuditLogger(  # type: ignore[attr-defined]
        config=AuditConfig(backend="file", file_path=str(audit_path)),
    )

    wall, lat = await _run_concurrent(agent, N_CONCURRENT)
    summary = _summarize("audit_file", wall, lat)
    print(f"  [WARNING] FileAuditStore uses sync open/write per event. "
          f"For high QPS, wrap with aiofiles or background queue.")


async def test_all_observability_enabled() -> None:
    """All 4 cross-cutting enabled simultaneously — production realistic scenario."""
    agent = _make_agent(
        budget_usd=100.0,
        rate_limit_rps=10_000.0,
        audit=True,
        trace=True,
    )
    wall, lat = await _run_concurrent(agent, N_CONCURRENT)
    _summarize("all_enabled", wall, lat)


# ---------------------------------------------------------------------------
# Overhead vs baseline comparison
# ---------------------------------------------------------------------------


async def test_overhead_comparison_report() -> None:
    """Print comparison summary table for human review."""
    print("\n\n  ─── Phase 8.8 Overhead Summary (N=%d concurrent) ───" % N_CONCURRENT)

    # Re-run to get clean numbers
    results = []

    agent = _make_agent()
    w, l = await _run_concurrent(agent, N_CONCURRENT)
    results.append(("baseline (no observability)", w * 1000, sorted(l)[len(l) // 2] * 1000, sorted(l)[int(len(l)*0.99)] * 1000))

    agent = _make_agent(budget_usd=1000.0, rate_limit_rps=10_000.0)
    w, l = await _run_concurrent(agent, N_CONCURRENT)
    results.append(("+ cost + rate (in-memory)", w * 1000, sorted(l)[len(l) // 2] * 1000, sorted(l)[int(len(l)*0.99)] * 1000))

    agent = _make_agent(audit=True, trace=True)
    w, l = await _run_concurrent(agent, N_CONCURRENT)
    results.append(("+ audit (console) + trace", w * 1000, sorted(l)[len(l) // 2] * 1000, sorted(l)[int(len(l)*0.99)] * 1000))

    print(f"\n  {'Setup':<35} {'wall(ms)':>10} {'p50(ms)':>10} {'p99(ms)':>10}")
    print("  " + "─" * 70)
    for label, w, p50, p99 in results:
        print(f"  {label:<35} {w:>10.1f} {p50:>10.2f} {p99:>10.2f}")
    print()
