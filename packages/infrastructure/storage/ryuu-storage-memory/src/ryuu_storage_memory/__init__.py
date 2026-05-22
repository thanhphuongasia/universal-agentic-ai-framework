"""ryuu-storage-memory — In-memory IKVStore + ICollectionStore."""

from ryuu_storage_memory.collection import InMemoryCollectionStore
from ryuu_storage_memory.kv import InMemoryKVStore

__version__ = "0.3.0a1"

__all__ = ["InMemoryKVStore", "InMemoryCollectionStore"]
