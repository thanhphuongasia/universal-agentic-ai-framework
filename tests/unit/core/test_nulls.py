"""RED tests for ryuu_core.nulls — will fail with ImportError until T09."""
import pytest
from ryuu_core.models import Cost
from ryuu_core.nulls import NullAuditLogger, NullCostTracker, NullRateLimiter, NullTracer
from ryuu_core.protocols import IAuditLogger, ICostTracker, IRateLimiter, ITracer


class TestNullCostTracker:
    def test_implements_protocol(self):
        assert isinstance(NullCostTracker(), ICostTracker)

    def test_record_is_noop(self):
        tracker = NullCostTracker()
        tracker.record("scope", Cost.zero())  # no exception

    def test_enforce_never_raises(self):
        tracker = NullCostTracker()
        tracker.enforce("scope", estimated=999.0)  # should not raise BudgetExceededError

    def test_summary_returns_zero_cost(self):
        tracker = NullCostTracker()
        result = tracker.summary("scope")
        assert isinstance(result, Cost)
        assert result.usd == 0.0


class TestNullTracer:
    def test_implements_protocol(self):
        assert isinstance(NullTracer(), ITracer)

    @pytest.mark.anyio
    async def test_span_is_context_manager(self):
        tracer = NullTracer()
        async with tracer.span("test-span"):
            pass  # no exception

    @pytest.mark.anyio
    async def test_span_yields_none(self):
        tracer = NullTracer()
        async with tracer.span("test") as val:
            assert val is None


class TestNullAuditLogger:
    def test_implements_protocol(self):
        assert isinstance(NullAuditLogger(), IAuditLogger)

    def test_log_start_noop(self):
        NullAuditLogger().log_start(object(), object())

    def test_log_complete_noop(self):
        NullAuditLogger().log_complete(object(), object())

    def test_log_error_noop(self):
        NullAuditLogger().log_error(object(), ValueError("x"))


class TestNullRateLimiter:
    def test_implements_protocol(self):
        assert isinstance(NullRateLimiter(), IRateLimiter)

    @pytest.mark.anyio
    async def test_acquire_does_not_block(self):
        limiter = NullRateLimiter()
        await limiter.acquire("scope", "agent-1")  # returns immediately
