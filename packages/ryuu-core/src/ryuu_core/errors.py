"""Tiered exception hierarchy and retry policy for RYUU.

Three tiers map directly to caller behavior:
- RetryableError  → exponential backoff, then re-raise
- DegradedError   → skip to cheaper fallback, log warning
- FatalError      → log error, escalate, never retry
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Literal

# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class FrameworkError(Exception):
    """Base for all RYUU framework errors."""


class RetryableError(FrameworkError):
    """Transient failure — caller should retry with exponential backoff."""


class DegradedError(FrameworkError):
    """Capability temporarily reduced — caller may fall back to a cheaper path."""


class FatalError(FrameworkError):
    """Non-recoverable — caller must log and escalate."""


class BudgetExceededError(DegradedError):
    """Cost budget exceeded for the given scope."""


class RateLimitTimeout(DegradedError):  # noqa: N818
    """Rate-limit acquire timed out."""


# ---------------------------------------------------------------------------
# Retry decision
# ---------------------------------------------------------------------------

_BACKOFF_SECONDS = [0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 30.0]
_JITTER_FRACTION = 0.2


@dataclass(frozen=True)
class RetryDecision:
    should_retry: bool
    wait_seconds: float | None
    tier: Literal["retryable", "degraded", "fatal"]


def retry_policy(exc: Exception, attempt: int = 0) -> RetryDecision:
    """Return the retry decision for *exc* after *attempt* prior tries.

    Jitter is applied to retryable decisions to prevent thundering-herd.
    """
    if isinstance(exc, RetryableError):
        base = _BACKOFF_SECONDS[min(attempt, len(_BACKOFF_SECONDS) - 1)]
        jitter = random.uniform(0, base * _JITTER_FRACTION)
        return RetryDecision(should_retry=True, wait_seconds=base + jitter, tier="retryable")

    if isinstance(exc, DegradedError):
        return RetryDecision(should_retry=False, wait_seconds=None, tier="degraded")

    return RetryDecision(should_retry=False, wait_seconds=None, tier="fatal")


# ---------------------------------------------------------------------------
# SDK error adapter
# ---------------------------------------------------------------------------


def classify_external_error(exc: Exception) -> FrameworkError:
    """Adapt an OpenAI/Anthropic SDK exception to the RYUU error tier.

    Preserves the original exception as the ``__cause__``.
    """
    module = type(exc).__module__ or ""
    name = type(exc).__name__.lower()

    is_ai_sdk = "openai" in module or "anthropic" in module

    def _retryable_err() -> RetryableError:
        err = RetryableError(str(exc))
        err.__cause__ = exc
        return err

    def _fatal_err() -> FatalError:
        err = FatalError(str(exc))
        err.__cause__ = exc
        return err

    if is_ai_sdk:
        _retryable_kws = ("ratelimit", "overloaded", "toomanyrequests")
        if any(tok in name for tok in _retryable_kws):
            return _retryable_err()
        _transient_kws = ("timeout", "connection", "network", "serviceunavailable")
        if any(tok in name for tok in _transient_kws):
            return _retryable_err()
        _fatal_kws = ("authentication", "permission", "forbidden", "unauthorized")
        if any(tok in name for tok in _fatal_kws):
            return _fatal_err()
        _bad_req_kws = ("badrequest", "invalidrequest", "unprocessable")
        # Some 400s are transient SDK bugs; treat as retryable.
        if any(tok in name for tok in _bad_req_kws):
            return _retryable_err()

    return _fatal_err()
