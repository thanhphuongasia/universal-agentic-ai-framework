"""asyncpg connection pool — one pool per (event loop, DSN).

Usage:
    pool = await get_pool(dsn)
    async with pool.acquire() as conn:
        await conn.execute(...)

    # test teardown:
    await close_all()

An asyncpg pool is bound to the event loop it was created on. Keying the cache
by the *running loop* (not just the DSN) keeps the pool reusable in a normal
single-loop server while staying correct when several loops exist — pytest
creates a fresh loop per test, Starlette's TestClient one per request. A stale
pool from a closed loop is never handed back: it would raise "Event loop is
closed" on use.
"""

from __future__ import annotations

import asyncio

import asyncpg

# Keyed by (id(running loop), dsn). One pool per loop per DSN.
_pools: dict[tuple[int, str], asyncpg.Pool] = {}


async def get_pool(dsn: str) -> asyncpg.Pool:
    """Return the pool for this DSN on the current event loop, or create one."""
    key = (id(asyncio.get_running_loop()), dsn)
    pool = _pools.get(key)
    if pool is None or pool.is_closing():
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)
        _pools[key] = pool
    return pool


async def close_all() -> None:
    """Close all pools and clear cache. Call in test teardown."""
    for pool in list(_pools.values()):
        try:
            await pool.close()
        except Exception:
            pass  # pool may belong to an already-closed loop — just drop it
    _pools.clear()
