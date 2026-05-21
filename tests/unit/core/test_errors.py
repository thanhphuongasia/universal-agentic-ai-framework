"""RED tests for ryuu_core.errors — will fail with ImportError until T06."""
import pytest
from ryuu_core.errors import (
    BudgetExceededError,
    DegradedError,
    FatalError,
    FrameworkError,
    RateLimitTimeout,
    RetryableError,
    RetryDecision,
    classify_external_error,
    retry_policy,
)


class TestErrorHierarchy:
    def test_retryable_is_framework_error(self):
        assert issubclass(RetryableError, FrameworkError)

    def test_degraded_is_framework_error(self):
        assert issubclass(DegradedError, FrameworkError)

    def test_fatal_is_framework_error(self):
        assert issubclass(FatalError, FrameworkError)

    def test_budget_exceeded_is_degraded(self):
        assert issubclass(BudgetExceededError, DegradedError)

    def test_rate_limit_timeout_is_degraded(self):
        assert issubclass(RateLimitTimeout, DegradedError)

    def test_all_catchable_as_exception(self):
        with pytest.raises(Exception):
            raise RetryableError("boom")


class TestRetryPolicy:
    def test_retryable_should_retry(self):
        decision = retry_policy(RetryableError("x"), attempt=0)
        assert decision.should_retry is True
        assert decision.wait_seconds is not None
        assert decision.tier == "retryable"

    def test_degraded_no_retry(self):
        decision = retry_policy(DegradedError("x"))
        assert decision.should_retry is False
        assert decision.tier == "degraded"

    def test_fatal_no_retry(self):
        decision = retry_policy(FatalError("x"))
        assert decision.should_retry is False
        assert decision.tier == "fatal"

    def test_retry_decision_is_frozen(self):
        d = RetryDecision(should_retry=True, wait_seconds=1.0, tier="retryable")
        with pytest.raises((AttributeError, TypeError)):
            d.should_retry = False  # type: ignore[misc]

    def test_backoff_increases_with_attempt(self):
        d0 = retry_policy(RetryableError("x"), attempt=0)
        d3 = retry_policy(RetryableError("x"), attempt=3)
        assert d3.wait_seconds > d0.wait_seconds  # type: ignore[operator]


class TestClassifyExternalError:
    def test_unknown_exception_becomes_fatal(self):
        result = classify_external_error(ValueError("bad"))
        assert isinstance(result, FatalError)

    def test_returns_framework_error(self):
        result = classify_external_error(RuntimeError("x"))
        assert isinstance(result, FrameworkError)
