"""PostgresHandlerStateStore — normalized settings + cumulative LLM stats.

Schema:
    handler_state: one row per scope_key with typed columns for settings and stats.

Replaces the IKVStore + JSON blob pattern used by RyuuHandler._load_state /
_save_state. Typed columns make schema evolution safe (ALTER TABLE ADD COLUMN
with a DEFAULT instead of migrating JSON blobs) and allow direct SQL queries
for cost/usage analytics.

Usage in RyuuHandler:
    store = PostgresHandlerStateStore(dsn=DATABASE_URL)
    state = await store.load("owner")
    state.model = "gpt-4o"
    await store.save("owner", state)
    # Per-turn stats — atomic increment avoids load+save race under concurrency:
    await store.increment_stats("owner", turns=1, input_tokens=200, output_tokens=80, usd=0.0004)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ryuu_storage_postgres._pool import get_pool


@dataclass
class HandlerState:
    """Mirrors RyuuHandler UserSettings + SessionStats as one flat record."""
    # settings
    model: str = "gpt-4o-mini"
    verbose: bool = False
    auto_compact: bool = True
    compact_threshold_tokens: int = 4000
    adaptive_routing: bool = False
    # cumulative stats
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_usd: float = 0.0


@dataclass
class PostgresHandlerStateStore:
    dsn: str
    table: str = "handler_state"
    _ready: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.table.replace("_", "").isalnum():
            raise ValueError(f"Invalid table name: {self.table!r}")

    async def _ensure_table(self) -> None:
        if self._ready:
            return
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.table} (
                    scope_key                TEXT PRIMARY KEY,
                    model                    TEXT NOT NULL DEFAULT 'gpt-4o-mini',
                    verbose                  BOOLEAN NOT NULL DEFAULT false,
                    auto_compact             BOOLEAN NOT NULL DEFAULT true,
                    compact_threshold_tokens INT NOT NULL DEFAULT 4000,
                    adaptive_routing         BOOLEAN NOT NULL DEFAULT false,
                    turns                    INT NOT NULL DEFAULT 0,
                    input_tokens             BIGINT NOT NULL DEFAULT 0,
                    output_tokens            BIGINT NOT NULL DEFAULT 0,
                    total_usd                NUMERIC(12,6) NOT NULL DEFAULT 0,
                    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
        self._ready = True

    async def load(self, scope_key: str) -> HandlerState:
        """Load state for scope; returns defaults if row does not exist."""
        await self._ensure_table()
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT model, verbose, auto_compact, compact_threshold_tokens,"
                f"       adaptive_routing, turns, input_tokens, output_tokens, total_usd"
                f" FROM {self.table} WHERE scope_key = $1",
                scope_key,
            )
            if row is None:
                return HandlerState()
            return HandlerState(
                model=row["model"],
                verbose=row["verbose"],
                auto_compact=row["auto_compact"],
                compact_threshold_tokens=row["compact_threshold_tokens"],
                adaptive_routing=row["adaptive_routing"],
                turns=row["turns"],
                input_tokens=row["input_tokens"],
                output_tokens=row["output_tokens"],
                total_usd=float(row["total_usd"]),
            )

    async def save(self, scope_key: str, state: HandlerState) -> None:
        """Upsert entire state (settings + stats) for a scope."""
        await self._ensure_table()
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            await conn.execute(
                f"INSERT INTO {self.table}"
                f" (scope_key, model, verbose, auto_compact, compact_threshold_tokens,"
                f"  adaptive_routing, turns, input_tokens, output_tokens, total_usd)"
                f" VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)"
                f" ON CONFLICT (scope_key) DO UPDATE SET"
                f"   model                    = EXCLUDED.model,"
                f"   verbose                  = EXCLUDED.verbose,"
                f"   auto_compact             = EXCLUDED.auto_compact,"
                f"   compact_threshold_tokens = EXCLUDED.compact_threshold_tokens,"
                f"   adaptive_routing         = EXCLUDED.adaptive_routing,"
                f"   turns                    = EXCLUDED.turns,"
                f"   input_tokens             = EXCLUDED.input_tokens,"
                f"   output_tokens            = EXCLUDED.output_tokens,"
                f"   total_usd                = EXCLUDED.total_usd,"
                f"   updated_at               = now()",
                scope_key,
                state.model, state.verbose, state.auto_compact,
                state.compact_threshold_tokens, state.adaptive_routing,
                state.turns, state.input_tokens, state.output_tokens, state.total_usd,
            )

    async def increment_stats(
        self,
        scope_key: str,
        *,
        turns: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        usd: float = 0.0,
    ) -> None:
        """Atomically increment LLM usage counters.

        Safer than load() → mutate → save() under concurrent turn processing,
        because the increment happens in a single SQL statement.
        """
        await self._ensure_table()
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            await conn.execute(
                f"INSERT INTO {self.table}(scope_key, turns, input_tokens, output_tokens, total_usd)"
                f" VALUES($1, $2, $3, $4, $5)"
                f" ON CONFLICT (scope_key) DO UPDATE SET"
                f"   turns         = {self.table}.turns + EXCLUDED.turns,"
                f"   input_tokens  = {self.table}.input_tokens + EXCLUDED.input_tokens,"
                f"   output_tokens = {self.table}.output_tokens + EXCLUDED.output_tokens,"
                f"   total_usd     = {self.table}.total_usd + EXCLUDED.total_usd,"
                f"   updated_at    = now()",
                scope_key, turns, input_tokens, output_tokens, usd,
            )

    async def delete(self, scope_key: str) -> None:
        await self._ensure_table()
        pool = await get_pool(self.dsn)
        async with pool.acquire() as conn:
            await conn.execute(
                f"DELETE FROM {self.table} WHERE scope_key = $1", scope_key
            )
