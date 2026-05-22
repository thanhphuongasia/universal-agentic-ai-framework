"""Token-bucket rate limiter per scope, async-safe via anyio."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import anyio

from ryuu_core.errors import RateLimitTimeout


@dataclass(frozen=True)
class RatePolicy:
    rps: float = 10.0
    burst: int = 20


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


class RateLimiter:
    """Async token-bucket rate limiter."""

    def __init__(self, policy: RatePolicy | None = None, store: IRateStore | None = None) -> None:
        self._policy = policy or RatePolicy()
        self._store = store or InMemoryRateStore()

    async def acquire(self, scope_key: str, agent_id: str = "", timeout: float | None = None) -> None:
        deadline = None if timeout is None else time.monotonic() + timeout
        backoff = 0.01

        while True:
            self._refill(scope_key)
            tokens = self._store.get_tokens(scope_key)

            if tokens >= 1.0:
                self._store.set_tokens(scope_key, tokens - 1.0)
                return

            if deadline is not None and time.monotonic() >= deadline:
                raise RateLimitTimeout(
                    f"Rate limit for scope {scope_key!r} / agent {agent_id!r} "
                    f"not satisfied within {timeout}s"
                )

            await anyio.sleep(backoff)
            backoff = min(backoff * 2, 1.0)

    def _refill(self, scope_key: str) -> None:
        now = time.monotonic()
        last = self._store.get_last_refill(scope_key)
        elapsed = now - last
        current = self._store.get_tokens(scope_key)

        if current == float("inf"):
            current = float(self._policy.burst)

        added = elapsed * self._policy.rps
        new_tokens = min(current + added, float(self._policy.burst))
        self._store.set_tokens(scope_key, new_tokens)
        self._store.set_last_refill(scope_key, now)

    def reset(self, scope_key: str) -> None:
        self._store.set_tokens(scope_key, float(self._policy.burst))
        self._store.set_last_refill(scope_key, time.monotonic())
