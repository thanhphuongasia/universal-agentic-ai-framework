"""Consumer-facing Protocol interfaces — zero dep, runtime-checkable."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ryuu_core.models import Cost


@runtime_checkable
class ICostTracker(Protocol):
    def record(self, scope: str, cost: "Cost") -> None: ...
    def enforce(self, scope: str, estimated: float) -> None: ...
    def summary(self, scope: str) -> "Cost": ...


@runtime_checkable
class ITracer(Protocol):
    def span(self, name: str, *args: Any, **kwargs: Any) -> AbstractAsyncContextManager[Any]: ...


@runtime_checkable
class IAuditLogger(Protocol):
    def log_start(self, task: Any, ctx: Any) -> None: ...
    def log_complete(self, task: Any, result: Any) -> None: ...
    def log_error(self, task: Any, exc: Exception) -> None: ...


@runtime_checkable
class IRateLimiter(Protocol):
    async def acquire(self, scope: str, agent_id: str) -> None: ...
