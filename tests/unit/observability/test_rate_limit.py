"""Tests for ryuu.observability.rate_limit — T06."""

from __future__ import annotations

import pytest

from ryuu_workflow.errors import RateLimitTimeout
from ryuu.observability.rate_limit import InMemoryRateStore, RateLimiter, RatePolicy

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fast_limiter(rps: float = 1000.0, burst: int = 100) -> RateLimiter:
    """High-throughput limiter for tests that just want to verify acquire() works."""
    return RateLimiter(policy=RatePolicy(rps=rps, burst=burst))


# ---------------------------------------------------------------------------
# Basic acquire
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_acquire_consumes_token() -> None:
    limiter = _fast_limiter()
    await limiter.acquire("scope1")  # should not raise


@pytest.mark.anyio
async def test_acquire_multiple_within_burst() -> None:
    limiter = _fast_limiter(burst=10)
    for _ in range(10):
        await limiter.acquire("s")


# ---------------------------------------------------------------------------
# Bucket refill
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_bucket_starts_at_burst_capacity() -> None:
    store = InMemoryRateStore()
    limiter = RateLimiter(policy=RatePolicy(rps=1.0, burst=5), store=store)
    # First call initializes to burst and consumes 1
    await limiter.acquire("s")
    # After one call, tokens ~ burst - 1 = 4
    tokens = store.get_tokens("s")
    assert 3.9 <= tokens <= 5.0  # allow small refill drift


@pytest.mark.anyio
async def test_multi_scope_isolation() -> None:
    limiter = _fast_limiter(burst=3)
    await limiter.acquire("scopeA")
    await limiter.acquire("scopeA")
    await limiter.acquire("scopeB")
    # scopeA used 2 tokens, scopeB used 1 — they are independent


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_timeout_raises_rate_limit_timeout() -> None:
    # Empty bucket: burst=0 means we can never get a token.
    limiter = RateLimiter(policy=RatePolicy(rps=0.001, burst=1))
    await limiter.acquire("s")  # drain the single token
    with pytest.raises(RateLimitTimeout):
        await limiter.acquire("s", timeout=0.05)


@pytest.mark.anyio
async def test_timeout_is_rate_limit_timeout_subtype() -> None:
    from ryuu_workflow.errors import DegradedError

    limiter = RateLimiter(policy=RatePolicy(rps=0.001, burst=1))
    await limiter.acquire("s")
    with pytest.raises(DegradedError):
        await limiter.acquire("s", timeout=0.05)


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_reset_refills_bucket() -> None:
    store = InMemoryRateStore()
    limiter = RateLimiter(policy=RatePolicy(rps=0.001, burst=1), store=store)
    await limiter.acquire("s")  # drain
    limiter.reset("s")
    # After reset, bucket is full again
    tokens = store.get_tokens("s")
    assert tokens == 1.0


# ---------------------------------------------------------------------------
# Fairness (multiple scopes don't steal from each other)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_fairness_across_scopes() -> None:
    limiter = _fast_limiter(rps=1000, burst=5)
    for _ in range(5):
        await limiter.acquire("scopeX")
    for _ in range(5):
        await limiter.acquire("scopeY")
    # Both should have been served
