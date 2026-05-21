"""ryuu-knowledge-rag — Phase 11 RAG pipeline for RYUU agents.

Public API:
  - `RecursiveChunker` (default chunker)
  - `InMemoryVectorStore` (default vector store)
  - `DenseRetriever` (cosine similarity)
  - `RAGPipeline` (chunk → embed → upsert; retrieve)
  - `RAGBackbone` (IKnowledgeBackbone impl, pluggable into Agent)

Production: swap `InMemoryVectorStore` for Chroma/Qdrant/Pinecone via
`IVectorStore` Protocol.
"""

from __future__ import annotations

from ryuu_knowledge_rag.backbone import RAGBackbone
from ryuu_knowledge_rag.chunker import Chunk, IChunker, RecursiveChunker
from ryuu_knowledge_rag.pipeline import DenseRetriever, IRetriever, RAGPipeline
from ryuu_knowledge_rag.vector_store import (
    InMemoryVectorStore,
    IVectorStore,
    SearchResult,
    VectorRecord,
)

__all__ = [
    "Chunk",
    "DenseRetriever",
    "IChunker",
    "InMemoryVectorStore",
    "IRetriever",
    "IVectorStore",
    "RAGBackbone",
    "RAGPipeline",
    "RecursiveChunker",
    "SearchResult",
    "VectorRecord",
]
