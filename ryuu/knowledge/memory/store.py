# Backward-compat shim — canonical source is ryuu_knowledge_memory.store
from ryuu_knowledge_memory.store import (  # noqa: F401
    IMemoryStore as IMemoryStore,
    MemoryEntry as MemoryEntry,
    MemoryLayer as MemoryLayer,
)
