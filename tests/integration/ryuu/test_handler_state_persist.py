"""Integration test — UserSettings persistence via PostgresHandlerStateStore.

Catches the class of bug where `_save_state` forgets to pass a settings field
to `HandlerState(...)` constructor. The dataclass default silently overrides
the in-memory value when saving, so the field appears to "reset" after restart.

Was originally caught when `streaming` toggle didn't persist (bug #4 in the
streaming chain): handler.py:_save_state was missing `streaming=s.streaming`
in the HandlerState constructor call.

Requires DATABASE_URL pointing to a real Postgres. Skipped otherwise.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from examples.ryuu_sensei.apps.ryuu_handler import RyuuHandler


def _load_dsn() -> str | None:
    """Read DATABASE_URL from env, falling back to ~/.ryuu/.env."""
    dsn = os.getenv("DATABASE_URL", "").strip()
    if dsn:
        return dsn
    env_path = Path.home() / ".ryuu" / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


DSN = _load_dsn()
pytestmark = pytest.mark.skipif(
    not DSN, reason="DATABASE_URL not set — Postgres integration test skipped"
)


@pytest.fixture
async def store():
    """Fresh PostgresHandlerStateStore + reset cached pool per test.

    asyncpg pools are cached globally by `get_pool()`; if the previous test's
    event loop closed, the pool is invalid for this test. Resetting per-test
    isolates connection state.
    """
    from ryuu_storage_postgres import _pool as pool_module
    from ryuu_storage_postgres import PostgresHandlerStateStore
    # Clear any cached pool from a previous test's event loop
    if hasattr(pool_module, "_pools"):
        pool_module._pools.clear()
    elif hasattr(pool_module, "_pool"):
        pool_module._pool = None
    st = PostgresHandlerStateStore(dsn=DSN)  # type: ignore[arg-type]
    yield st


@pytest.fixture
async def handler(store):
    """Handler wired to real Postgres store."""
    return RyuuHandler(memory_backbone=None, normalized_state_store=store)


SCOPE = "_pytest_persist_scope"


async def _reset_and_reload(handler: RyuuHandler, scope: str) -> None:
    """Simulate bot restart: clear in-memory state, reload from DB."""
    handler._state_loaded.discard(scope)
    handler.settings.pop(scope, None)
    await handler._load_state(scope)


async def test_streaming_persists_after_reload(handler, store):
    """Toggle streaming on → save → reload → still on (regression for bug #4)."""
    await store.delete(SCOPE)
    try:
        await handler.set_streaming(SCOPE, True)
        await _reset_and_reload(handler, SCOPE)
        assert handler.get_settings(SCOPE).streaming is True
    finally:
        await store.delete(SCOPE)


async def test_streaming_off_persists(handler, store):
    """Toggle streaming off → save → reload → still off."""
    await store.delete(SCOPE)
    try:
        await handler.set_streaming(SCOPE, True)
        await handler.set_streaming(SCOPE, False)
        await _reset_and_reload(handler, SCOPE)
        assert handler.get_settings(SCOPE).streaming is False
    finally:
        await store.delete(SCOPE)


async def test_adaptive_routing_persists(handler, store):
    """adaptive_routing toggle persists across reload."""
    await store.delete(SCOPE)
    try:
        await handler.set_adaptive_routing(SCOPE, True)
        await _reset_and_reload(handler, SCOPE)
        assert handler.get_settings(SCOPE).adaptive_routing is True
    finally:
        await store.delete(SCOPE)


async def test_all_settings_round_trip(handler, store):
    """All UserSettings fields survive save → reload round-trip.

    Guards against future fields being added to UserSettings/HandlerState
    but forgotten in _save_state's HandlerState(...) call.
    """
    await store.delete(SCOPE)
    try:
        await handler.set_streaming(SCOPE, True)
        await handler.set_adaptive_routing(SCOPE, True)
        await handler.set_verbose(SCOPE, True)
        await handler.set_auto_compact(SCOPE, False)
        await handler.set_compact_threshold(SCOPE, 8000)
        await handler.set_model(SCOPE, "gpt-4o")

        await _reset_and_reload(handler, SCOPE)
        s = handler.get_settings(SCOPE)
        assert s.streaming is True
        assert s.adaptive_routing is True
        assert s.verbose is True
        assert s.auto_compact is False
        assert s.compact_threshold_tokens == 8000
        assert s.model == "gpt-4o"
    finally:
        await store.delete(SCOPE)
