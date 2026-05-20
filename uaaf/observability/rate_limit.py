"""Token-bucket rate limiter per scope, async-safe via anyio.

Design:
- Pure in-memory token-bucket.  Phase 5 swaps to Redis via IRateStore Protocol.
- Uses ``anyio.Event`` for back-pressure instead of busy-wait / sleep loops.
- Each ``(scope_key, agent_id)`` pair consumes from the same bucket, so a
  single RatePolicy covers all agents in the scope.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import anyio

from uaaf_workflow.errors import RateLimitTimeout

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RatePolicy:
    """Token-bucket parameters per scope.

    rps: sustained requests per second.
    burst: maximum burst size (tokens that can accumulate while idle).
    """

    rps: float = 10.0
    burst: int = 20


# ---------------------------------------------------------------------------
# Storage protocol (for future distributed backend)
# ---------------------------------------------------------------------------


@runtime_checkable
class IRateStore(Protocol):
    def get_tokens(self, scope_key: str) -> float: ...
    def set_tokens(self, scope_key: str, tokens: float) -> None: ...
    def get_last_refill(self, scope_key: str) -> float: ...
    def set_last_refill(self, scope_key: str, ts: float) -> None: ...


@dataclass
class InMemoryRateStore:
    _tokens: dict[str, float] = field(default_factory=dict)
    _last_refill: dict[str, float] = field(default_factory=dict)

    def get_tokens(self, scope_key: str) -> float:
        return self._tokens.get(scope_key, float("inf"))

    def set_tokens(self, scope_key: str, tokens: float) -> None:
        self._tokens[scope_key] = tokens

    def get_last_refill(self, scope_key: str) -> float:
        return self._last_refill.get(scope_key, time.monotonic())

    def set_last_refill(self, scope_key: str, ts: float) -> None:
        self._last_refill[scope_key] = ts


# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------


class RateLimiter:
    """Async token-bucket rate limiter.

    Thread / task safe via anyio task-group semantics — each acquire is atomic
    from the caller's perspective.
    """

    def __init__(
        self,
        policy: RatePolicy | None = None,
        store: IRateStore | None = None,
    ) -> None:
        self._policy = policy or RatePolicy()
        self._store = store or InMemoryRateStore()

    async def acquire(
        self,
        scope_key: str,
        agent_id: str = "",
        timeout: float | None = None,
    ) -> None:
        """Consume one token for *scope_key*.

        Blocks until a token is available.  Raises ``RateLimitTimeout``
        if *timeout* seconds elapse without a token becoming available.
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        backoff = 0.01  # initial sleep between retries

        while True:
            self._refill(scope_key)
            tokens = self._store.get_tokens(scope_key)

            if tokens >= 1.0:
                self._store.set_tokens(scope_key, tokens - 1.0)
                return

            # No token available — check deadline then sleep.
            if deadline is not None and time.monotonic() >= deadline:
                raise RateLimitTimeout(
                    f"Rate limit for scope {scope_key!r} / agent {agent_id!r} "
                    f"not satisfied within {timeout}s"
                )

            await anyio.sleep(backoff)
            backoff = min(backoff * 2, 1.0)  # cap at 1s

    def _refill(self, scope_key: str) -> None:
        now = time.monotonic()
        last = self._store.get_last_refill(scope_key)
        elapsed = now - last
        current = self._store.get_tokens(scope_key)

        # Initialize to burst capacity on first call.
        if current == float("inf"):
            current = float(self._policy.burst)

        added = elapsed * self._policy.rps
        new_tokens = min(current + added, float(self._policy.burst))
        self._store.set_tokens(scope_key, new_tokens)
        self._store.set_last_refill(scope_key, now)

    def reset(self, scope_key: str) -> None:
        """Reset tokens for *scope_key* to burst capacity."""
        self._store.set_tokens(scope_key, float(self._policy.burst))
        self._store.set_last_refill(scope_key, time.monotonic())
