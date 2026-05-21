"""RAGPipeline + IRetriever — Phase 11.

Chunk → embed → upsert (ingest). Query → embed → vector_store.search (retrieve).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ryuu_providers.llm import ILLMProvider

from ryuu_knowledge_rag.chunker import Chunk, IChunker, RecursiveChunker
from ryuu_knowledge_rag.vector_store import (
    InMemoryVectorStore,
    IVectorStore,
    SearchResult,
    VectorRecord,
)


@runtime_checkable
class IRetriever(Protocol):
    """Semantic retrieval contract."""

    async def retrieve(self, query: str, top_k: int = 5) -> list[SearchResult]: ...


@dataclass
class DenseRetriever:
    """Embed query → cosine search in vector store.

    Default `IRetriever` impl. For hybrid (sparse + dense) or reranking, wrap
    this with custom IRetriever calling DenseRetriever then post-processing.
    """

    embedder: ILLMProvider
    vector_store: IVectorStore
    embed_model: str = "text-embedding-3-small"

    async def retrieve(self, query: str, top_k: int = 5) -> list[SearchResult]:
        emb = await self.embedder.embed(query, model=self.embed_model)
        return await self.vector_store.search(emb.vector, top_k=top_k)


@dataclass
class RAGPipeline:
    """End-to-end RAG pipeline. Ingest docs + retrieve.

    Usage::

        pipeline = RAGPipeline(
            embedder=OpenAIProvider(api_key=...),
            vector_store=InMemoryVectorStore(),     # or Chroma/Qdrant
            chunker=RecursiveChunker(chunk_size=1500),
        )
        await pipeline.ingest(documents=["doc 1 text...", "doc 2..."])
        hits = await pipeline.retrieve("question?", top_k=3)
    """

    embedder: ILLMProvider
    vector_store: IVectorStore = field(default_factory=InMemoryVectorStore)
    chunker: IChunker = field(default_factory=RecursiveChunker)
    embed_model: str = "text-embedding-3-small"

    async def ingest(
        self,
        documents: list[str] | list[dict[str, Any]],
        scope_key: str = "default",
    ) -> int:
        """Chunk + embed + upsert. Returns count of chunks stored.

        `documents` can be list of strings OR list of dicts with `text` + `metadata`.
        """
        all_chunks: list[Chunk] = []
        for i, doc in enumerate(documents):
            if isinstance(doc, dict):
                text = str(doc["text"])
                meta = {"scope_key": scope_key, "doc_index": i, **doc.get("metadata", {})}
            else:
                text = str(doc)
                meta = {"scope_key": scope_key, "doc_index": i}
            all_chunks.extend(self.chunker.chunk(text, metadata=meta))

        # Embed all chunks (sequential — providers can batch internally)
        records: list[VectorRecord] = []
        for chunk in all_chunks:
            emb = await self.embedder.embed(chunk.text, model=self.embed_model)
            records.append(VectorRecord(
                id=str(uuid.uuid4()),
                text=chunk.text,
                vector=emb.vector,
                metadata=chunk.metadata,
            ))

        await self.vector_store.upsert(records)
        return len(records)

    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        scope_key: str | None = None,
    ) -> list[SearchResult]:
        """Embed query → top-k cosine search. Filter by scope_key if provided."""
        emb = await self.embedder.embed(query, model=self.embed_model)
        filter_ = {"scope_key": scope_key} if scope_key else None
        return await self.vector_store.search(emb.vector, top_k=top_k, filter_metadata=filter_)


__all__ = ["IRetriever", "DenseRetriever", "RAGPipeline"]
