"""ryuu-knowledge-memory — Memory backbone + quality layer.

Core:
    MemoryBackbone               composes Working + Episodic stores
    WorkingMemoryStore           recent (FIFO, max 50)
    EpisodicMemoryStore          longer-term (keyword overlap scoring + lifecycle)
    SemanticMemoryStore          long-term consolidated facts (written by DreamingConsolidator)
    MemoryEntry, MemoryLayer     value types
    IMemoryStore                 Protocol
    MemoryToolset                pre-built remember/recall/list_memories tools

Quality layer (optional — pass to MemoryBackbone):
    ExtractionFilter             LLM-based signal/noise filter for episodic writes
    DreamingConsolidator         episodic → semantic consolidation (post-session)
    EvictionJob                  importance-weighted decay + archive cleanup

Conversational glue (over WorkingMemoryStore):
    ConversationMemory           record (Q,A) turns + recall recent-exchange block
    TurnFormat                   injectable wording/limits so each app keeps its voice
"""

from ryuu_knowledge_memory.backbone import MemoryBackbone
from ryuu_knowledge_memory.consolidator import DreamingConsolidator, EvictionJob, ExtractionFilter
from ryuu_knowledge_memory.conversation_memory import ConversationMemory, TurnFormat
from ryuu_knowledge_memory.episodic import EpisodicMemoryStore
from ryuu_knowledge_memory.semantic import SemanticMemoryStore
from ryuu_knowledge_memory.store import IMemoryStore, MemoryEntry, MemoryLayer
from ryuu_knowledge_memory.tools import MemoryToolset
from ryuu_knowledge_memory.working import WorkingMemoryStore

__version__ = "0.3.0a2"

__all__ = [
    "ConversationMemory",
    "DreamingConsolidator",
    "EpisodicMemoryStore",
    "EvictionJob",
    "ExtractionFilter",
    "IMemoryStore",
    "MemoryBackbone",
    "MemoryEntry",
    "MemoryLayer",
    "MemoryToolset",
    "SemanticMemoryStore",
    "TurnFormat",
    "WorkingMemoryStore",
]
