"""Tests for PostgresSessionStore, PostgresHandlerStateStore, PostgresProfileStore.

Requires a live Postgres instance. Skipped automatically when DATABASE_URL is not set.

Run:
    DATABASE_URL=postgresql://postgres:test@localhost/ryuu_test pytest tests/test_normalized_stores.py
"""

from __future__ import annotations

import os
import uuid

import pytest

from ryuu_storage_postgres import close_all
from ryuu_storage_postgres._pool import get_pool
from ryuu_storage_postgres.session import PostgresSessionStore
from ryuu_storage_postgres.handler_state import PostgresHandlerStateStore, HandlerState
from ryuu_storage_postgres.profile import PostgresProfileStore
from ryuu_messaging_core.protocols import Session, Turn

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL not set — skipping Postgres tests",
)

DSN = os.getenv("DATABASE_URL", "")


def _scope() -> str:
    """Generate a unique scope_key so tests never collide."""
    return f"test_{uuid.uuid4().hex}"


@pytest.fixture(autouse=True)
async def cleanup():
    yield
    await close_all()


# ---------------------------------------------------------------------------
# Helpers — ensure tables are created once per fixture
# ---------------------------------------------------------------------------

@pytest.fixture
async def session_store():
    store = PostgresSessionStore(dsn=DSN)
    await store._ensure_tables()
    return store


@pytest.fixture
async def handler_store():
    store = PostgresHandlerStateStore(dsn=DSN)
    await store._ensure_table()
    return store


@pytest.fixture
async def profile_store():
    store = PostgresProfileStore(dsn=DSN)
    await store._ensure_table()
    return store


# ---------------------------------------------------------------------------
# PostgresSessionStore
# ---------------------------------------------------------------------------

class TestPostgresSessionStore:

    async def test_load_creates_fresh_session(self, session_store):
        """load_or_create on an empty DB returns a new Session with no history."""
        sk = _scope()
        session = await session_store.load_or_create(
            sk, channel="tg", sender_id="u1", conversation_id="c1"
        )
        assert session.scope_key == sk
        assert session.channel == "tg"
        assert session.sender_id == "u1"
        assert session.conversation_id == "c1"
        assert session.history == []

    async def test_save_and_reload(self, session_store):
        """Save a session with 3 turns; reload preserves them in order."""
        sk = _scope()
        session = Session(
            scope_key=sk,
            channel="tg",
            sender_id="u2",
            conversation_id="c2",
            history=[
                Turn(role="user", text="Hello"),
                Turn(role="assistant", text="Hi there"),
                Turn(role="user", text="How are you?"),
            ],
        )
        await session_store.save(session)

        reloaded = await session_store.load_or_create(
            sk, channel="tg", sender_id="u2", conversation_id="c2"
        )
        assert len(reloaded.history) == 3
        assert reloaded.history[0].role == "user"
        assert reloaded.history[0].text == "Hello"
        assert reloaded.history[1].role == "assistant"
        assert reloaded.history[1].text == "Hi there"
        assert reloaded.history[2].role == "user"
        assert reloaded.history[2].text == "How are you?"

    async def test_max_turns_respected(self, session_store):
        """Save 25 turns with max_turns=20; reload returns only the last 20."""
        sk = _scope()
        turns = [Turn(role="user" if i % 2 == 0 else "assistant", text=f"msg{i}") for i in range(25)]
        session = Session(
            scope_key=sk,
            channel="tg",
            sender_id="u3",
            conversation_id="c3",
            history=turns,
            max_turns=20,
        )
        await session_store.save(session)

        # The store itself stores whatever is in session.history. The max_turns
        # window is enforced on load. We need to simulate a large stored history
        # by saving all 25 turns (bypassing the window) and confirming load caps at 20.
        # Since save() writes session.history as-is, store 25 rows directly.
        pool = await get_pool(DSN)
        async with pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM session_turns WHERE scope_key = $1", sk
            )
        # The save stored exactly what was in history (25 turns)
        assert count == 25

        reloaded = await session_store.load_or_create(
            sk, channel="tg", sender_id="u3", conversation_id="c3"
        )
        assert len(reloaded.history) == 20
        # The last 20 in chronological order → msg5 through msg24
        assert reloaded.history[0].text == "msg5"
        assert reloaded.history[-1].text == "msg24"

    async def test_extra_roundtrip(self, session_store):
        """session.extra dict survives save/reload without data loss."""
        sk = _scope()
        extra_data = {"carry_steer": ["be concise"], "hitl": True, "count": 42}
        session = Session(
            scope_key=sk,
            channel="tg",
            sender_id="u4",
            conversation_id="c4",
            extra=extra_data,
        )
        await session_store.save(session)

        reloaded = await session_store.load_or_create(
            sk, channel="tg", sender_id="u4", conversation_id="c4"
        )
        assert reloaded.extra["carry_steer"] == ["be concise"]
        assert reloaded.extra["hitl"] is True
        assert reloaded.extra["count"] == 42

    async def test_version_increments(self, session_store):
        """Saving 3 times results in version = 3 in the DB."""
        sk = _scope()
        session = Session(
            scope_key=sk, channel="tg", sender_id="u5", conversation_id="c5"
        )
        await session_store.save(session)
        await session_store.save(session)
        await session_store.save(session)

        pool = await get_pool(DSN)
        async with pool.acquire() as conn:
            version = await conn.fetchval(
                "SELECT version FROM sessions WHERE scope_key = $1", sk
            )
        assert version == 3

    async def test_delete_cascades(self, session_store):
        """Deleting a scope removes the session row and all its turns."""
        sk = _scope()
        session = Session(
            scope_key=sk,
            channel="tg",
            sender_id="u6",
            conversation_id="c6",
            history=[Turn(role="user", text="bye")],
        )
        await session_store.save(session)
        await session_store.delete(sk)

        pool = await get_pool(DSN)
        async with pool.acquire() as conn:
            sess_count = await conn.fetchval(
                "SELECT COUNT(*) FROM sessions WHERE scope_key = $1", sk
            )
            turn_count = await conn.fetchval(
                "SELECT COUNT(*) FROM session_turns WHERE scope_key = $1", sk
            )
        assert sess_count == 0
        assert turn_count == 0

    async def test_all_keys(self, session_store):
        """all_keys returns all saved scope keys."""
        sk1 = _scope()
        sk2 = _scope()
        for sk in (sk1, sk2):
            await session_store.save(
                Session(scope_key=sk, channel="tg", sender_id="u", conversation_id="c")
            )
        keys = list(await session_store.all_keys())
        assert sk1 in keys
        assert sk2 in keys
        # Cleanup
        for sk in (sk1, sk2):
            await session_store.delete(sk)


# ---------------------------------------------------------------------------
# PostgresHandlerStateStore
# ---------------------------------------------------------------------------

class TestPostgresHandlerStateStore:

    async def test_load_defaults(self, handler_store):
        """Loading a non-existent scope returns HandlerState with defaults."""
        sk = _scope()
        state = await handler_store.load(sk)
        assert state.model == "gpt-4o-mini"
        assert state.verbose is False
        assert state.auto_compact is True
        assert state.turns == 0
        assert state.total_usd == 0.0

    async def test_save_and_reload(self, handler_store):
        """Save with custom model + verbose=True, reload verifies the values."""
        sk = _scope()
        state = HandlerState(model="gpt-4o", verbose=True, adaptive_routing=True)
        await handler_store.save(sk, state)

        loaded = await handler_store.load(sk)
        assert loaded.model == "gpt-4o"
        assert loaded.verbose is True
        assert loaded.adaptive_routing is True
        # Cleanup
        await handler_store.delete(sk)

    async def test_increment_stats_atomic(self, handler_store):
        """increment_stats called twice accumulates totals correctly."""
        sk = _scope()
        await handler_store.increment_stats(
            sk, turns=1, input_tokens=100, output_tokens=50, usd=0.0002
        )
        await handler_store.increment_stats(
            sk, turns=1, input_tokens=200, output_tokens=80, usd=0.0004
        )

        state = await handler_store.load(sk)
        assert state.turns == 2
        assert state.input_tokens == 300
        assert state.output_tokens == 130
        assert abs(state.total_usd - 0.0006) < 1e-8
        # Cleanup
        await handler_store.delete(sk)

    async def test_save_preserves_stats(self, handler_store):
        """save() with explicit stats; reload confirms they are not lost."""
        sk = _scope()
        state = HandlerState(
            model="gpt-4o-mini",
            turns=10,
            input_tokens=5000,
            output_tokens=2000,
            total_usd=0.01,
        )
        await handler_store.save(sk, state)

        loaded = await handler_store.load(sk)
        assert loaded.turns == 10
        assert loaded.input_tokens == 5000
        assert loaded.output_tokens == 2000
        assert abs(loaded.total_usd - 0.01) < 1e-8
        # Cleanup
        await handler_store.delete(sk)

    async def test_delete(self, handler_store):
        """Deleting a scope causes the next load to return defaults."""
        sk = _scope()
        await handler_store.save(sk, HandlerState(model="gpt-4o", turns=5))
        await handler_store.delete(sk)

        state = await handler_store.load(sk)
        assert state.model == "gpt-4o-mini"
        assert state.turns == 0


# ---------------------------------------------------------------------------
# PostgresProfileStore
# ---------------------------------------------------------------------------

class TestPostgresProfileStore:

    async def test_set_and_get_current(self, profile_store):
        """set_value + get_current returns the stored value."""
        sk = _scope()
        await profile_store.set_value(sk, "name", "Alice")
        current = await profile_store.get_current(sk)
        assert current["name"] == "Alice"
        # Cleanup
        await profile_store.delete_scope(sk)

    async def test_set_creates_history(self, profile_store):
        """Setting the same key twice creates 2 history rows."""
        sk = _scope()
        await profile_store.set_value(sk, "goal", "Learn Python")
        await profile_store.set_value(sk, "goal", "Ship UAAF")
        history = await profile_store.get_history(sk, "goal")
        assert len(history) == 2
        # Cleanup
        await profile_store.delete_scope(sk)

    async def test_old_row_closed(self, profile_store):
        """After a second set, the first row has valid_to set (not NULL)."""
        sk = _scope()
        await profile_store.set_value(sk, "goal", "Learn Python")
        await profile_store.set_value(sk, "goal", "Ship UAAF")

        history = await profile_store.get_history(sk, "goal")
        # Newest first — history[0] is the current one (valid_to IS NULL)
        assert history[0].valid_to is None
        assert history[0].value == "Ship UAAF"
        # Older row has valid_to set
        assert history[1].valid_to is not None
        assert history[1].value == "Learn Python"
        # Cleanup
        await profile_store.delete_scope(sk)

    async def test_get_current_only_active(self, profile_store):
        """After 2 sets, get_current returns only the latest value."""
        sk = _scope()
        await profile_store.set_value(sk, "lang", "Python")
        await profile_store.set_value(sk, "lang", "TypeScript")

        current = await profile_store.get_current(sk)
        assert current["lang"] == "TypeScript"
        assert len(current) == 1
        # Cleanup
        await profile_store.delete_scope(sk)

    async def test_as_prompt_block_empty(self, profile_store):
        """as_prompt_block returns empty string when no profile exists."""
        sk = _scope()
        result = await profile_store.as_prompt_block(sk)
        assert result == ""

    async def test_as_prompt_block_with_data(self, profile_store):
        """as_prompt_block includes 'User profile:' header and bullet points."""
        sk = _scope()
        await profile_store.set_value(sk, "name", "Alice")
        await profile_store.set_value(sk, "goal", "Ship UAAF")

        block = await profile_store.as_prompt_block(sk)
        assert block.startswith("User profile:")
        assert "• name: Alice" in block
        assert "• goal: Ship UAAF" in block
        # Cleanup
        await profile_store.delete_scope(sk)

    async def test_delete_key(self, profile_store):
        """delete_key removes one key; others are unaffected."""
        sk = _scope()
        await profile_store.set_value(sk, "name", "Alice")
        await profile_store.set_value(sk, "goal", "Ship UAAF")
        await profile_store.delete_key(sk, "goal")

        current = await profile_store.get_current(sk)
        assert "goal" not in current
        assert current["name"] == "Alice"
        # Cleanup
        await profile_store.delete_scope(sk)

    async def test_delete_scope(self, profile_store):
        """delete_scope wipes all keys; get_current returns {}."""
        sk = _scope()
        await profile_store.set_value(sk, "name", "Alice")
        await profile_store.set_value(sk, "goal", "Ship UAAF")
        await profile_store.delete_scope(sk)

        current = await profile_store.get_current(sk)
        assert current == {}

    async def test_temporal_isolation_between_scopes(self, profile_store):
        """Scope A and scope B profile data do not bleed into each other."""
        sk_a = _scope()
        sk_b = _scope()
        await profile_store.set_value(sk_a, "name", "Alice")
        await profile_store.set_value(sk_b, "name", "Bob")

        a_current = await profile_store.get_current(sk_a)
        b_current = await profile_store.get_current(sk_b)

        assert a_current["name"] == "Alice"
        assert b_current["name"] == "Bob"
        # Cleanup
        await profile_store.delete_scope(sk_a)
        await profile_store.delete_scope(sk_b)
