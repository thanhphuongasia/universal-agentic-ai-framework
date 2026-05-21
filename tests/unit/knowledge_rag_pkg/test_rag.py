"""Phase 11 — ryuu-knowledge-rag tests.

16 cases covering chunker, vector store, pipeline, backbone.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from ryuu_knowledge_rag import (
    DenseRetriever,
    InMemoryVectorStore,
    RAGBackbone,
    RAGPipeline,
    RecursiveChunker,
    VectorRecord,
)


# ---------------------------------------------------------------------------
# Fake embedder — deterministic mock matching ILLMProvider.embed signature
# ---------------------------------------------------------------------------


@dataclass
class _FakeEmbedder:
    """Deterministic embeddings: hash text → vector for testing search."""

    provider_id: str = "fake-embed"
    dim: int = 32

    async def embed(self, text: str, model: str | None = None):
        from ryuu_providers.llm import Embedding
        # Hash-based deterministic vector. Same text → same vector → top similarity.
        import hashlib
        h = hashlib.md5(text.encode()).digest()
        vec = [((h[i % len(h)] / 255.0) * 2 - 1) for i in range(self.dim)]
        return Embedding(vector=vec, model=model or "fake")

    async def complete(self, request):
        raise NotImplementedError

    async def stream(self, request):
        raise NotImplementedError

    def estimate_cost(self, request):
        from ryuu_core.models import Cost
        return Cost(input_tokens=0, output_tokens=0, usd=0.0, provider="fake", model="fake")


# ---------------------------------------------------------------------------
# Chunker tests
# ---------------------------------------------------------------------------


def test_chunker_short_text_single_chunk() -> None:
    chunker = RecursiveChunker(chunk_size=1500)
    chunks = chunker.chunk("short text")
    assert len(chunks) == 1
    assert chunks[0].text == "short text"


def test_chunker_long_text_multiple_chunks() -> None:
    chunker = RecursiveChunker(chunk_size=100, overlap=20)
    text = "Paragraph one.\n\n" + "x" * 200 + "\n\nParagraph two."
    chunks = chunker.chunk(text)
    assert len(chunks) >= 2
    # Each chunk includes index metadata
    assert all("chunk_index" in c.metadata for c in chunks)


def test_chunker_empty_returns_empty() -> None:
    assert RecursiveChunker().chunk("") == []


def test_chunker_metadata_preserved() -> None:
    chunks = RecursiveChunker().chunk("hello", metadata={"src": "doc1"})
    assert chunks[0].metadata["src"] == "doc1"


# ---------------------------------------------------------------------------
# Vector store tests
# ---------------------------------------------------------------------------


async def test_vector_store_upsert_and_count() -> None:
    store = InMemoryVectorStore()
    assert await store.count() == 0
    await store.upsert([
        VectorRecord(id="1", text="hello", vector=[1.0, 0.0, 0.0]),
        VectorRecord(id="2", text="world", vector=[0.0, 1.0, 0.0]),
    ])
    assert await store.count() == 2


async def test_vector_store_cosine_search_returns_top_k() -> None:
    store = InMemoryVectorStore()
    await store.upsert([
        VectorRecord(id="a", text="apple", vector=[1.0, 0.0, 0.0]),
        VectorRecord(id="b", text="banana", vector=[0.0, 1.0, 0.0]),
        VectorRecord(id="c", text="cherry", vector=[0.0, 0.0, 1.0]),
    ])
    # Query closest to "apple" vector
    hits = await store.search([1.0, 0.1, 0.0], top_k=2)
    assert len(hits) == 2
    assert hits[0].record.id == "a"
    assert hits[0].score > hits[1].score


async def test_vector_store_metadata_filter() -> None:
    store = InMemoryVectorStore()
    await store.upsert([
        VectorRecord(id="1", text="A", vector=[1.0, 0.0], metadata={"src": "x"}),
        VectorRecord(id="2", text="B", vector=[1.0, 0.0], metadata={"src": "y"}),
    ])
    hits = await store.search([1.0, 0.0], top_k=5, filter_metadata={"src": "y"})
    assert len(hits) == 1
    assert hits[0].record.id == "2"


async def test_vector_store_delete() -> None:
    store = InMemoryVectorStore()
    await store.upsert([VectorRecord(id="1", text="a", vector=[1.0])])
    assert await store.count() == 1
    await store.delete(["1"])
    assert await store.count() == 0


async def test_vector_store_empty_search_returns_empty() -> None:
    store = InMemoryVectorStore()
    assert await store.search([1.0, 0.0], top_k=5) == []


# ---------------------------------------------------------------------------
# Pipeline tests
# ---------------------------------------------------------------------------


async def test_pipeline_ingest_creates_chunks_and_records() -> None:
    pipeline = RAGPipeline(
        embedder=_FakeEmbedder(),
        vector_store=InMemoryVectorStore(),
        chunker=RecursiveChunker(chunk_size=1500),
    )
    count = await pipeline.ingest(["doc one", "doc two"])
    assert count == 2   # 2 short docs → 1 chunk each


async def test_pipeline_retrieve_returns_results() -> None:
    pipeline = RAGPipeline(embedder=_FakeEmbedder())
    await pipeline.ingest(["Python is a programming language"])
    hits = await pipeline.retrieve("Python", top_k=1)
    assert len(hits) == 1


async def test_pipeline_ingest_dict_with_metadata() -> None:
    pipeline = RAGPipeline(embedder=_FakeEmbedder())
    await pipeline.ingest([
        {"text": "hello world", "metadata": {"src": "doc1"}},
    ])
    hits = await pipeline.retrieve("hello", top_k=1)
    assert hits[0].record.metadata.get("src") == "doc1"


async def test_pipeline_scope_filtering() -> None:
    pipeline = RAGPipeline(embedder=_FakeEmbedder())
    await pipeline.ingest(["docs"], scope_key="user_a")
    await pipeline.ingest(["other"], scope_key="user_b")
    hits = await pipeline.retrieve("docs", top_k=5, scope_key="user_a")
    assert all(h.record.metadata.get("scope_key") == "user_a" for h in hits)


async def test_dense_retriever_works() -> None:
    store = InMemoryVectorStore()
    retriever = DenseRetriever(embedder=_FakeEmbedder(), vector_store=store)
    await store.upsert([VectorRecord(id="1", text="hello", vector=[0.5] * 32)])
    hits = await retriever.retrieve("hello", top_k=1)
    assert len(hits) == 1


# ---------------------------------------------------------------------------
# RAGBackbone tests (IKnowledgeBackbone impl)
# ---------------------------------------------------------------------------


async def test_backbone_write_and_query() -> None:
    backbone = RAGBackbone(pipeline=RAGPipeline(embedder=_FakeEmbedder()))
    await backbone.write("Python is awesome", scope_key="docs")
    result = await backbone.query("Python", scope_key="docs", top_k=1)
    assert len(result.results) == 1
    assert "Python" in result.results[0]


async def test_backbone_assemble_context_respects_budget() -> None:
    backbone = RAGBackbone(pipeline=RAGPipeline(embedder=_FakeEmbedder()))
    # Ingest 5 docs, each ~50 chars
    for i in range(5):
        await backbone.write(f"Document number {i} with extra content here", scope_key="d")

    ctx = await backbone.assemble_context("number", scope_key="d", budget_tokens=20)
    # 20 tokens × 4 chars/token = 80 chars budget → ~1-2 docs fit
    assert ctx.token_count <= 30   # close to budget (allow first chunk fully)
    assert len(ctx.source_ids) >= 1


async def test_backbone_scope_isolation() -> None:
    backbone = RAGBackbone(pipeline=RAGPipeline(embedder=_FakeEmbedder()))
    await backbone.write("Alice's doc", scope_key="alice")
    await backbone.write("Bob's doc", scope_key="bob")

    alice_result = await backbone.query("doc", scope_key="alice", top_k=5)
    bob_result = await backbone.query("doc", scope_key="bob", top_k=5)
    assert all("Alice" in r for r in alice_result.results)
    assert all("Bob" in r for r in bob_result.results)
