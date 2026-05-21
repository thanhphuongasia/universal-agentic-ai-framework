"""Tests for ryuu.observability.errors — T02."""

from __future__ import annotations

from ryuu_workflow.errors import (
    BudgetExceededError,
    DegradedError,
    FatalError,
    FrameworkError,
    RateLimitTimeout,
    RetryableError,
    classify_external_error,
    retry_policy,
)

# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


def test_retryable_is_framework_error() -> None:
    assert isinstance(RetryableError("oops"), FrameworkError)


def test_degraded_is_framework_error() -> None:
    assert isinstance(DegradedError("oops"), FrameworkError)


def test_fatal_is_framework_error() -> None:
    assert isinstance(FatalError("oops"), FrameworkError)


def test_budget_exceeded_is_degraded() -> None:
    assert isinstance(BudgetExceededError("over"), DegradedError)


def test_rate_limit_timeout_is_degraded() -> None:
    assert isinstance(RateLimitTimeout("slow"), DegradedError)


# ---------------------------------------------------------------------------
# retry_policy — tier decisions
# ---------------------------------------------------------------------------


def test_retry_policy_retryable_should_retry() -> None:
    decision = retry_policy(RetryableError("transient"))
    assert decision.should_retry is True
    assert decision.tier == "retryable"
    assert decision.wait_seconds is not None and decision.wait_seconds > 0


def test_retry_policy_degraded_no_retry() -> None:
    decision = retry_policy(DegradedError("degraded"))
    assert decision.should_retry is False
    assert decision.tier == "degraded"
    assert decision.wait_seconds is None


def test_retry_policy_fatal_no_retry() -> None:
    decision = retry_policy(FatalError("dead"))
    assert decision.should_retry is False
    assert decision.tier == "fatal"
    assert decision.wait_seconds is None


def test_retry_policy_plain_exception_is_fatal() -> None:
    decision = retry_policy(ValueError("unexpected"))
    assert decision.should_retry is False
    assert decision.tier == "fatal"


# ---------------------------------------------------------------------------
# retry_policy — backoff math
# ---------------------------------------------------------------------------


def test_retry_policy_backoff_increases_with_attempts() -> None:
    decisions = [retry_policy(RetryableError("t"), attempt=i) for i in range(6)]
    # Strip jitter to compare minimums: each attempt's base must be >= prior
    # (We only compare base values indirectly via lower bound.)
    for i in range(1, len(decisions)):
        assert decisions[i].wait_seconds is not None
        assert decisions[i - 1].wait_seconds is not None
        # base always increases or stays at max (30s); jitter is bounded
        assert decisions[i].wait_seconds >= decisions[i - 1].wait_seconds - 6  # loose bound


def test_retry_policy_jitter_within_bounds() -> None:
    base_at_0 = 0.5
    jitter_max = base_at_0 * 0.2
    for _ in range(50):  # statistical: any run should pass
        d = retry_policy(RetryableError("t"), attempt=0)
        assert d.wait_seconds is not None
        assert base_at_0 <= d.wait_seconds <= base_at_0 + jitter_max + 1e-9


def test_retry_policy_max_backoff_capped() -> None:
    # attempt=100 should not exceed 30 + jitter
    d = retry_policy(RetryableError("t"), attempt=100)
    assert d.wait_seconds is not None
    assert d.wait_seconds <= 30 * (1 + 0.2) + 1e-9  # 30s + max 20% jitter


# ---------------------------------------------------------------------------
# classify_external_error
# ---------------------------------------------------------------------------


class _FakeRateLimitError(Exception):
    """Mimic openai.RateLimitError."""

    __module__ = "openai"


class _FakeTimeoutError(Exception):
    """Mimic openai.APITimeoutError."""

    __module__ = "openai"


class _FakeAuthError(Exception):
    """Mimic anthropic.AuthenticationError."""

    __module__ = "anthropic"


class _FakeBadRequestError(Exception):
    """Mimic openai.BadRequestError."""

    __module__ = "openai"


class _FakeUnknownError(Exception):
    """Unknown origin."""

    __module__ = "myapp"


def test_classify_rate_limit_is_retryable() -> None:
    # Class name "_FakeRateLimitError" already contains "ratelimit" in lowercase.
    exc = _FakeRateLimitError("rate limit")
    result = classify_external_error(exc)
    assert isinstance(result, RetryableError)
    assert result.__cause__ is exc


def test_classify_timeout_is_retryable() -> None:
    class TimeoutStub(Exception):  # noqa: N818
        __module__ = "openai"

    err = TimeoutStub("timed out")
    err.__class__.__name__ = "TimeoutError"
    result = classify_external_error(err)
    assert isinstance(result, RetryableError)


def test_classify_auth_error_is_fatal() -> None:
    class AuthStub(Exception):  # noqa: N818
        __module__ = "anthropic"

    err = AuthStub("bad key")
    err.__class__.__name__ = "AuthenticationError"
    result = classify_external_error(err)
    assert isinstance(result, FatalError)


def test_classify_unknown_origin_is_fatal() -> None:
    result = classify_external_error(_FakeUnknownError("??"))
    assert isinstance(result, FatalError)


def test_classify_preserves_cause() -> None:
    orig = _FakeUnknownError("original")
    result = classify_external_error(orig)
    assert result.__cause__ is orig
