"""ryuu-knowledge-memory — Memory backbone + tools.

Public API:
    MemoryBackbone               composes Working + Episodic stores
    WorkingMemoryStore           recent (FIFO, max 50)
    EpisodicMemoryStore          longer-term (keyword overlap scoring)
    MemoryEntry, MemoryLayer     value types
    IMemoryStore                 Protocol
    MemoryToolset                pre-built remember/recall/list_memories tools
"""

from ryuu_knowledge_memory.backbone import MemoryBackbone
from ryuu_knowledge_memory.episodic import EpisodicMemoryStore
from ryuu_knowledge_memory.store import IMemoryStore, MemoryEntry, MemoryLayer
from ryuu_knowledge_memory.tools import MemoryToolset
from ryuu_knowledge_memory.working import WorkingMemoryStore

__version__ = "0.3.0a1"

__all__ = [
    "EpisodicMemoryStore",
    "IMemoryStore",
    "MemoryBackbone",
    "MemoryEntry",
    "MemoryLayer",
    "MemoryToolset",
    "WorkingMemoryStore",
]
