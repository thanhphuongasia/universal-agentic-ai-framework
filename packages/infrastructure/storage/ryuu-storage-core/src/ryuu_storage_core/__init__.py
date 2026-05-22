"""ryuu-storage-core — Protocols + value types for storage backends.

    from ryuu_storage_core import (
        IKVStore, ICollectionStore, IBlobStore,
        Item,
        StorageError, StorageConnectionError, StorageNotFoundError,
    )

Backends live in sibling packages:
    ryuu-storage-memory   InMemoryKVStore, InMemoryCollectionStore
    ryuu-storage-sqlite   SqliteKVStore, SqliteCollectionStore
    (future) ryuu-storage-postgres, -redis, -s3, -dynamodb, …
"""

from ryuu_storage_core.protocols import (
    IBlobStore,
    ICollectionStore,
    IKVStore,
    Item,
    StorageConnectionError,
    StorageError,
    StorageNotFoundError,
)

__version__ = "0.3.0a1"

__all__ = [
    "IBlobStore",
    "ICollectionStore",
    "IKVStore",
    "Item",
    "StorageConnectionError",
    "StorageError",
    "StorageNotFoundError",
]
