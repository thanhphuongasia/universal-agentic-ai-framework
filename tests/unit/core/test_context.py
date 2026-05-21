"""RED tests for ryuu_core.context — will fail with ImportError until T06."""
import dataclasses

import pytest
from ryuu_core.context import ContextScope, ExecutionContext


class TestContextScope:
    def test_scope_key_format(self):
        scope = ContextScope(user_id="u1", session_id="s1", domain="chat")
        assert scope.scope_key == "chat:u1:s1"

    def test_scope_key_with_tenant(self):
        scope = ContextScope(user_id="u1", session_id="s1", domain="chat", tenant_id="t1")
        assert "t1" in scope.scope_key

    def test_scope_is_frozen(self):
        scope = ContextScope(user_id="u1", session_id="s1", domain="chat")
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            scope.user_id = "other"  # type: ignore[misc]

    def test_tenant_id_defaults_none(self):
        scope = ContextScope(user_id="u", session_id="s", domain="d")
        assert scope.tenant_id is None


class TestExecutionContext:
    def test_construction_minimal(self):
        scope = ContextScope(user_id="u1", session_id="s1", domain="test")
        ctx = ExecutionContext(scope=scope, correlation_id="corr-1")
        assert ctx.correlation_id == "corr-1"
        assert ctx.budget_remaining_usd is None
        assert ctx.strategy_id is None

    def test_is_frozen(self):
        scope = ContextScope(user_id="u1", session_id="s1", domain="test")
        ctx = ExecutionContext(scope=scope, correlation_id="corr-1")
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            ctx.correlation_id = "other"  # type: ignore[misc]

    def test_replace_creates_new_instance(self):
        scope = ContextScope(user_id="u1", session_id="s1", domain="test")
        ctx = ExecutionContext(scope=scope, correlation_id="corr-1")
        ctx2 = dataclasses.replace(ctx, strategy_id="react")
        assert ctx2.strategy_id == "react"
        assert ctx.strategy_id is None  # original unchanged
