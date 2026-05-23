"""asyncpg connection pool — one pool per DSN, shared across all store instances.

Usage:
    pool = await get_pool(dsn)
    async with pool.acquire() as conn:
        await conn.execute(...)

    # test teardown:
    await close_all()
"""

from __future__ import annotations

import asyncpg

_pools: dict[str, asyncpg.Pool] = {}


async def get_pool(dsn: str) -> asyncpg.Pool:
    """Return existing pool for DSN, or create one (min=1, max=5)."""
    if dsn not in _pools:
        _pools[dsn] = await asyncpg.create_pool(dsn, min_size=1, max_size=5)
    return _pools[dsn]


async def close_all() -> None:
    """Close all pools and clear cache. Call in test teardown."""
    for pool in list(_pools.values()):
        await pool.close()
    _pools.clear()
