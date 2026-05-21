"""RED tests for ryuu_observability.audit, tracer, rate_limit."""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------

def test_audit_logger_import() -> None:
    from ryuu_observability.audit import AuditConfig, AuditLogger
    logger = AuditLogger(AuditConfig(backend="console"))
    assert logger is not None


def test_audit_logger_log_start() -> None:
    from ryuu_observability.audit import AuditConfig, AuditLogger
    logger = AuditLogger(AuditConfig(backend="console"))
    logger.log_start("t1", "agent1", "scope:x", "corr-123")
    assert logger.last_chain_hash() != ""


def test_verify_chain_import() -> None:
    from ryuu_observability.audit import verify_chain
    assert verify_chain([]) is True


# ---------------------------------------------------------------------------
# tracer
# ---------------------------------------------------------------------------

def test_tracer_import() -> None:
    from ryuu_observability.tracer import Tracer, get_current_correlation_id
    t = Tracer(service_name="test-service")
    assert t is not None
    t.shutdown()


@pytest.mark.asyncio
async def test_tracer_span_yields_correlation_id() -> None:
    from ryuu_observability.tracer import Tracer
    t = Tracer(service_name="test")
    async with t.span("test-op") as corr_id:
        assert isinstance(corr_id, str)
        assert len(corr_id) > 0
    t.shutdown()


# ---------------------------------------------------------------------------
# rate_limit
# ---------------------------------------------------------------------------

def test_rate_limiter_import() -> None:
    from ryuu_observability.rate_limit import RateLimiter, RatePolicy
    rl = RateLimiter(policy=RatePolicy(rps=10.0, burst=20))
    assert rl is not None


@pytest.mark.asyncio
async def test_rate_limiter_acquire_succeeds() -> None:
    from ryuu_observability.rate_limit import RateLimiter, RatePolicy
    rl = RateLimiter(policy=RatePolicy(rps=100.0, burst=10))
    await rl.acquire("scope:test")  # should not raise


@pytest.mark.asyncio
async def test_rate_limiter_timeout_raises() -> None:
    from ryuu_core.errors import RateLimitTimeout
    from ryuu_observability.rate_limit import RateLimiter, RatePolicy

    # Very low rps + zero burst → immediate timeout
    rl = RateLimiter(policy=RatePolicy(rps=0.001, burst=0))
    with pytest.raises(RateLimitTimeout):
        await rl.acquire("scope:tight", timeout=0.05)
