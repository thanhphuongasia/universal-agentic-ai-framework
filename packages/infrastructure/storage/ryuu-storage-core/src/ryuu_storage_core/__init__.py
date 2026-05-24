"""ryuu-storage-core — Protocols + value types for storage backends.

    from ryuu_storage_core import (
        IKVStore, ICollectionStore, IBlobStore,
        IProfileStore,
        Item, ProfileEntry,
        StorageError, StorageConnectionError, StorageNotFoundError,
    )

Backends live in sibling packages:
    ryuu-storage-memory   InMemoryKVStore, InMemoryCollectionStore
    ryuu-storage-sqlite   SqliteKVStore, SqliteCollectionStore
    ryuu-storage-postgres PostgresKVStore, PostgresCollectionStore,
                          PostgresSessionStore, PostgresHandlerStateStore,
                          PostgresProfileStore
"""

from ryuu_storage_core.protocols import (
    IBlobStore,
    ICollectionStore,
    IKVStore,
    IProfileStore,
    Item,
    ProfileEntry,
    StorageConnectionError,
    StorageError,
    StorageNotFoundError,
)

__version__ = "0.3.0a1"

__all__ = [
    "IBlobStore",
    "ICollectionStore",
    "IKVStore",
    "IProfileStore",
    "Item",
    "ProfileEntry",
    "StorageConnectionError",
    "StorageError",
    "StorageNotFoundError",
]
