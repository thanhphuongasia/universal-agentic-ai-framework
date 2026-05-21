"""RED tests for ryuu_core.protocols — will fail with ImportError until T08."""
from typing import runtime_checkable

import pytest
from ryuu_core.protocols import IAuditLogger, ICostTracker, IRateLimiter, ITracer


class TestProtocolsAreRuntimeCheckable:
    def test_icost_tracker_is_protocol(self):
        assert hasattr(ICostTracker, "__protocol_attrs__") or hasattr(
            ICostTracker, "_is_protocol"
        )

    def test_itracer_is_protocol(self):
        assert hasattr(ITracer, "__protocol_attrs__") or hasattr(ITracer, "_is_protocol")

    def test_iaudit_logger_is_protocol(self):
        assert hasattr(IAuditLogger, "__protocol_attrs__") or hasattr(
            IAuditLogger, "_is_protocol"
        )

    def test_irate_limiter_is_protocol(self):
        assert hasattr(IRateLimiter, "__protocol_attrs__") or hasattr(
            IRateLimiter, "_is_protocol"
        )


class TestProtocolSignatures:
    def test_icost_tracker_has_record(self):
        assert "record" in dir(ICostTracker)

    def test_icost_tracker_has_enforce(self):
        assert "enforce" in dir(ICostTracker)

    def test_itracer_has_span(self):
        assert "span" in dir(ITracer)

    def test_iaudit_logger_has_log_start(self):
        assert "log_start" in dir(IAuditLogger)

    def test_irate_limiter_has_acquire(self):
        assert "acquire" in dir(IRateLimiter)
