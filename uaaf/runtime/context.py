"""ExecutionContext and ContextScope — the identity bundle for every request."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContextScope:
    """Immutable identity of a single request context.

    scope_key is used as the dict key for cost/rate buckets.
    """

    user_id: str
    session_id: str
    domain: str
    tenant_id: str | None = None

    @property
    def scope_key(self) -> str:
        parts = [self.domain, self.user_id, self.session_id]
        if self.tenant_id:
            parts.append(self.tenant_id)
        return ":".join(parts)


@dataclass(frozen=True)
class ExecutionContext:
    """Immutable bundle of identity + budget passed to every agent execute call.

    Use dataclasses.replace(ctx, field=value) to create modified copies.
    strategy_id is populated by RequestHandler before dispatching to a strategy.
    """

    scope: ContextScope
    correlation_id: str
    budget_remaining_usd: float | None = None
    strategy_id: str | None = None
