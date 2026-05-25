"""PostgresSessionStore — ISessionStore on top of asyncpg.

Schema:
    sessions:      scope-level metadata (channel, sender_id, extra bag, optimistic version)
    session_turns: individual turns — 1 row per turn, FK → sessions ON DELETE CASCADE

Differences from KVSessionStore (blob):
  • Turns are queryable rows, not a JSON array inside a text column
  • extra (dispatcher state, carry_steer, HITL, etc.) stays JSONB — always read as a unit
  • version column provides optimistic-lock safety against concurrent saves
  • All historical turns are kept in DB; load_or_create returns only the last max_turns
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable

from ryuu_messaging_core.protocols import Session, Turn

from ryuu_storage_postgres._pool import get_pool


@dataclass
class PostgresSessionStore:
    """Normalized session store: sessions table + session_turns table."""

    dsn: str
    max_turns: int = 20
    _ready: bool = field(default=False, init=False, repr=False)

    async def _ensure_tables(self) -> None:
        if self._ready:
            return
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            # Migration guard: if sessions table exists with the old KV schema
            # (has column "key", no column "scope_key"), drop it so we can
            # recreate with the normalized schema. Old blob data has no value.
            cols = await conn.fetch(
                "SELECT column_name FROM information_schema.columns"
                " WHERE table_name = 'sessions' AND table_schema = 'public'"
            )
            col_names = {r["column_name"] for r in cols}
            if col_names and "key" in col_names and "scope_key" not in col_names:
                await conn.execute("DROP TABLE IF EXISTS sessions CASCADE")

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    scope_key       TEXT PRIMARY KEY,
                    channel         TEXT NOT NULL,
                    sender_id       TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    max_turns       INT NOT NULL DEFAULT 20,
                    extra           JSONB DEFAULT '{}',
                    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
                    version         INT NOT NULL DEFAULT 0
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS session_turns (
                    id         BIGSERIAL PRIMARY KEY,
                    scope_key  TEXT NOT NULL
                               REFERENCES sessions(scope_key) ON DELETE CASCADE,
                    "role"     TEXT NOT NULL CHECK ("role" IN
                               ('user', 'assistant', 'system', 'summary', 'tool')),
                    text       TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS session_turns_scope_time
                ON session_turns(scope_key, id DESC)
            """)
            # Migration for existing tables: relax the role CHECK to admit
            # compaction summaries (LLMCompactor emits role='summary') and
            # future system/tool turns. Drop + re-add the constraint.
            await conn.execute(
                "ALTER TABLE session_turns"
                " DROP CONSTRAINT IF EXISTS session_turns_role_check"
            )
            await conn.execute(
                "ALTER TABLE session_turns ADD CONSTRAINT session_turns_role_check"
                " CHECK (\"role\" IN ('user', 'assistant', 'system', 'summary', 'tool'))"
            )
        self._ready = True

    async def load_or_create(
        self,
        scope_key: str,
        channel: str,
        sender_id: str,
        conversation_id: str,
    ) -> Session:
        await self._ensure_tables()
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT scope_key, channel, sender_id, conversation_id, max_turns, extra"
                " FROM sessions WHERE scope_key = $1",
                scope_key,
            )
            if row is None:
                return Session(
                    scope_key=scope_key,
                    channel=channel,
                    sender_id=sender_id,
                    conversation_id=conversation_id,
                    max_turns=self.max_turns,
                )

            max_turns = row["max_turns"]
            extra: dict[str, Any] = row["extra"] or {}
            if isinstance(extra, str):
                extra = json.loads(extra)

            # Load last max_turns turns in chronological order via DESC subquery
            turn_rows = await conn.fetch(
                'SELECT "role", text FROM ('
                '  SELECT "role", text, id FROM session_turns'
                "  WHERE scope_key = $1 ORDER BY id DESC LIMIT $2"
                ") sub ORDER BY id ASC",
                scope_key, max_turns,
            )
            history = [Turn(role=r["role"], text=r["text"]) for r in turn_rows]

            return Session(
                scope_key=row["scope_key"],
                channel=row["channel"],
                sender_id=row["sender_id"],
                conversation_id=row["conversation_id"],
                history=history,
                max_turns=max_turns,
                extra=extra,
            )

    async def save(self, session: Session) -> None:
        await self._ensure_tables()
        pool = await get_pool(self.dsn)
        extra_json = json.dumps(session.extra, ensure_ascii=False)
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Upsert session metadata; increment version for optimistic tracking
                await conn.execute(
                    "INSERT INTO sessions"
                    " (scope_key, channel, sender_id, conversation_id, max_turns, extra, version)"
                    " VALUES($1, $2, $3, $4, $5, $6::jsonb, 1)"
                    " ON CONFLICT (scope_key) DO UPDATE SET"
                    "   channel         = EXCLUDED.channel,"
                    "   sender_id       = EXCLUDED.sender_id,"
                    "   conversation_id = EXCLUDED.conversation_id,"
                    "   max_turns       = EXCLUDED.max_turns,"
                    "   extra           = EXCLUDED.extra,"
                    "   updated_at      = now(),"
                    "   version         = sessions.version + 1",
                    session.scope_key, session.channel, session.sender_id,
                    session.conversation_id, session.max_turns, extra_json,
                )
                # Replace current turns with the session's in-memory window.
                # Historical turns beyond max_turns are NOT preserved — session.history
                # is already a rolling window. A separate append-only conversation_log
                # table can be added later for full audit history.
                await conn.execute(
                    "DELETE FROM session_turns WHERE scope_key = $1",
                    session.scope_key,
                )
                if session.history:
                    await conn.executemany(
                        'INSERT INTO session_turns(scope_key, "role", text)'
                        " VALUES($1, $2, $3)",
                        [(session.scope_key, t.role, t.text) for t in session.history],
                    )

    async def delete(self, scope_key: str) -> None:
        await self._ensure_tables()
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            # ON DELETE CASCADE removes session_turns automatically
            await conn.execute(
                "DELETE FROM sessions WHERE scope_key = $1", scope_key
            )

    async def all_keys(self) -> Iterable[str]:
        await self._ensure_tables()
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT scope_key FROM sessions ORDER BY scope_key"
            )
            return [r["scope_key"] for r in rows]
