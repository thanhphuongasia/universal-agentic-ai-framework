"""Storage Protocols — three access patterns, many possible backends.

  • IKVStore           key → string value
  • ICollectionStore   append + query items per scope
  • IBlobStore         large binary objects with optional signed URLs

Consumer packages (messaging, knowledge-memory, app stores) depend on ONLY
these Protocols. Backends (sqlite, postgres, redis, s3, …) each ship as a
separate package implementing one or more of these.

Design notes:
  - All values are `str` (JSON-encoded at the consumer's discretion). Keeps
    the protocols simple and the wire format obvious for debugging.
  - `table` is a logical namespace within a backend (SQLite table name,
    Postgres schema/table, Redis key prefix, DynamoDB table). Two stores
    can share one DB file by using different table names.
  - All methods are async even when backends are sync-stdlib (sqlite3) —
    wrap with `asyncio.to_thread` inside the adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Item:
    """One row in an ICollectionStore."""
    id: str
    scope_key: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0    # unix epoch seconds; 0 = unknown


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class StorageError(Exception):
    """Base class for all storage backend errors."""


class StorageConnectionError(StorageError):
    """Backend connection / authentication failure."""


class StorageNotFoundError(StorageError):
    """Item or key does not exist (raised only by methods that promise it)."""


# ---------------------------------------------------------------------------
# IKVStore — key → string value
# ---------------------------------------------------------------------------

@runtime_checkable
class IKVStore(Protocol):
    """Key-value store with JSON-string values.

    Consumer pattern: serialize structured data with json.dumps, store as str.
    The backend doesn't care about the JSON shape — just that it's a string.
    """
    table: str   # logical namespace within the backend

    async def get(self, key: str) -> str | None:
        """Return value or None if key absent. Never raises on missing key."""
        ...

    async def put(self, key: str, value: str) -> None:
        """Upsert — overwrites existing value."""
        ...

    async def delete(self, key: str) -> bool:
        """Returns True if a row was removed, False if key was absent."""
        ...

    async def keys(self, prefix: str = "") -> Iterable[str]:
        """Iterate keys (optionally filtered by prefix). For listing 'all todos
        of user X', call with prefix=f'todo:{user_id}:'."""
        ...

    async def close(self) -> None:
        """Release connections / file handles. Idempotent."""
        ...


# ---------------------------------------------------------------------------
# ICollectionStore — append + scan + search per scope_key
# ---------------------------------------------------------------------------

@runtime_checkable
class ICollectionStore(Protocol):
    """Append-mostly collection of Items, partitioned by scope_key.

    For memory entries, audit logs, event streams. Items are individually
    addressable by id (returned from append) so they can be updated/deleted,
    but the dominant access pattern is append + list/search.
    """
    table: str

    async def append(
        self,
        scope_key: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Append a new item. Returns the generated item id."""
        ...

    async def get(self, scope_key: str, item_id: str) -> Item | None:
        """Fetch single item by id within a scope. None if absent."""
        ...

    async def update(
        self,
        scope_key: str,
        item_id: str,
        content: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Partial update. Returns True if item existed, False otherwise."""
        ...

    async def delete(self, scope_key: str, item_id: str) -> bool:
        """Returns True if removed, False if absent."""
        ...

    async def list(
        self,
        scope_key: str,
        limit: int = 100,
        since_id: str | None = None,
    ) -> list[Item]:
        """List items in append order. `since_id` cursors past prior items."""
        ...

    async def search(
        self,
        scope_key: str,
        query: str,
        top_k: int = 5,
    ) -> list[Item]:
        """Keyword search within a scope. Backend semantics vary:
           - sqlite: keyword overlap (BM25 in future)
           - postgres: tsvector / pg_trgm
           - elastic: real full-text"""
        ...

    async def clear(self, scope_key: str) -> None:
        """Delete every item for one scope."""
        ...

    async def close(self) -> None: ...


# ---------------------------------------------------------------------------
# IBlobStore — large binary objects
# ---------------------------------------------------------------------------

@runtime_checkable
class IBlobStore(Protocol):
    """Large binary objects (attachments, embeddings, vector blobs).

    Distinct from IKVStore because:
      - Values can be GB-scale; need streaming, range reads, signed URLs
      - Filesystem / S3 / GCS impls don't naturally fit IKVStore semantics
    """

    async def put(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload. Returns canonical URI (e.g. 's3://bucket/key' or 'file:///…')."""
        ...

    async def get(self, key: str) -> bytes | None: ...

    async def delete(self, key: str) -> bool: ...

    async def url(self, key: str, expires_sec: int = 3600) -> str | None:
        """Presigned URL where supported (S3, GCS). None for filesystem."""
        ...

    async def close(self) -> None: ...
