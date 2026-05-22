"""Shared SQLite connection helper.

One connection per (db_path) — reused across stores that share a DB file.
Uses WAL mode for better concurrent-read behavior. Sync sqlite3 calls run
inside `asyncio.to_thread` to keep the event loop unblocked.
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from pathlib import Path
from typing import Any

# Module-level connection cache keyed by (resolved) db_path. Lets a KV store
# and a Collection store on the same DB file share one connection — which
# matters because SQLite's WAL mode allows many readers but one writer; using
# one connection per process avoids "database is locked" surprises.
_connections: dict[str, sqlite3.Connection] = {}
_lock = threading.Lock()


def _resolve(db_path: str | Path) -> str:
    p = Path(db_path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """Get or create a shared connection for a DB file.

    Connection has WAL mode + foreign keys enabled. Caller MUST NOT close it
    directly — the cache outlives individual store instances.
    """
    key = _resolve(db_path)
    with _lock:
        conn = _connections.get(key)
        if conn is None:
            conn = sqlite3.connect(
                key,
                isolation_level=None,            # autocommit; explicit BEGIN where needed
                check_same_thread=False,         # we serialize via asyncio.to_thread
            )
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("PRAGMA foreign_keys = ON")
            _connections[key] = conn
        return conn


async def run(fn: Any, *args: Any) -> Any:
    """Run a sync callable in the default executor — keeps the event loop free."""
    return await asyncio.to_thread(fn, *args)


def close_all() -> None:
    """For tests — drop all cached connections."""
    with _lock:
        for c in _connections.values():
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass
        _connections.clear()
