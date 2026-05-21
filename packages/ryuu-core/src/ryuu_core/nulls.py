"""NullObject defaults for all ryuu-core Protocols.

Use in tests or TrustLevel.LOW domains where no-op behaviour is correct.
Production code injects real implementations via constructor.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncGenerator

from ryuu_core.models import Cost

if TYPE_CHECKING:
    pass


class NullCostTracker:
    """No-op ICostTracker — never raises, summary returns Cost.zero()."""

    def record(self, scope: str, cost: Cost) -> None:
        pass

    def enforce(self, scope: str, estimated: float) -> None:
        pass

    def summary(self, scope: str) -> Cost:
        return Cost.zero()


class NullTracer:
    """No-op ITracer — span() is a no-op async context manager."""

    @asynccontextmanager
    async def span(self, name: str, *args: Any, **kwargs: Any) -> AsyncGenerator[None, None]:
        yield


class NullAuditLogger:
    """No-op IAuditLogger — all log methods are no-ops.

    Accepts both positional and keyword args to be compatible with any
    calling convention (agent.py uses kwargs, test code uses positional).
    """

    def log_start(self, *args: Any, **kwargs: Any) -> None:
        pass

    def log_complete(self, *args: Any, **kwargs: Any) -> None:
        pass

    def log_error(self, *args: Any, **kwargs: Any) -> None:
        pass


class NullRateLimiter:
    """No-op IRateLimiter — acquire() returns immediately."""

    async def acquire(self, scope: str, agent_id: str) -> None:
        pass
