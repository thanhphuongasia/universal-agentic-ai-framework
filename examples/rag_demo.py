"""Phase 11 RAG Demo — ingest docs → query → assemble context.

Run:
    OPENAI_API_KEY=sk-... python -m examples.rag_demo    # real embeddings
    python -m examples.rag_demo                            # FakeEmbedder demo
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from dataclasses import dataclass

from ryuu_knowledge_rag import (
    InMemoryVectorStore,
    RAGBackbone,
    RAGPipeline,
    RecursiveChunker,
)


@dataclass
class _FakeEmbedder:
    """Deterministic mock for demo without API key."""

    provider_id: str = "fake"

    async def embed(self, text: str, model: str | None = None):
        from ryuu_providers.llm import Embedding
        h = hashlib.md5(text.encode()).digest()
        vec = [((h[i % len(h)] / 255.0) * 2 - 1) for i in range(32)]
        return Embedding(vector=vec, model=model or "fake")

    async def complete(self, request): raise NotImplementedError
    async def stream(self, request): raise NotImplementedError
    def estimate_cost(self, request):
        from ryuu_core.models import Cost
        return Cost(input_tokens=0, output_tokens=0, usd=0.0, provider="fake", model="fake")


KNOWLEDGE_BASE = [
    "Python is a high-level, interpreted programming language known for clean syntax and readability.",
    "RYUU is a Universal Agentic AI Framework with composable building blocks for agents.",
    "Phase 14 added Claude-like Thinking patterns: thinking_mode, BestOfN, AdaptiveStrategy.",
    "RAG (Retrieval-Augmented Generation) combines vector search with LLM generation for grounded answers.",
    "ryuu-cognitive package contains ICognitiveStrategy implementations like ReAct and Evaluator.",
    "Factory Agent() supports 4 prompt modes and 4 tool modes for ergonomic single-agent setup.",
]


async def main() -> None:
    has_key = bool(os.getenv("OPENAI_API_KEY"))
    print("=" * 70)
    print(f"  Phase 11 RAG Demo — {'OpenAI embeddings' if has_key else 'FakeEmbedder'}")
    print("=" * 70)

    if has_key:
        from ryuu._provider_detect import build_provider
        embedder = build_provider("gpt-4o-mini")
    else:
        embedder = _FakeEmbedder()

    # ── 1. Build RAG pipeline ────────────────────────────────────────────
    pipeline = RAGPipeline(
        embedder=embedder,
        vector_store=InMemoryVectorStore(),
        chunker=RecursiveChunker(chunk_size=200, overlap=30),
    )

    # ── 2. Ingest 6 docs (chunks + embeds + upserts) ─────────────────────
    print("\n[1] Ingesting knowledge base...")
    count = await pipeline.ingest(KNOWLEDGE_BASE, scope_key="kb")
    print(f"    → {count} chunks stored")

    # ── 3. Query (top-k semantic search) ─────────────────────────────────
    queries = [
        "What is RYUU?",
        "How does adaptive compute work?",
        "Tell me about Python syntax",
    ]
    print("\n[2] Semantic queries:")
    for q in queries:
        hits = await pipeline.retrieve(q, top_k=2, scope_key="kb")
        print(f"\n    Q: {q}")
        for h in hits:
            print(f"      [{h.score:.3f}] {h.record.text[:80]}...")

    # ── 4. RAGBackbone wraps pipeline as IKnowledgeBackbone ──────────────
    print("\n[3] RAGBackbone (IKnowledgeBackbone impl):")
    backbone = RAGBackbone(pipeline=pipeline)
    ctx = await backbone.assemble_context(
        "What is RYUU framework?",
        scope_key="kb",
        budget_tokens=100,
    )
    print(f"    Assembled context ({ctx.token_count} tokens, {len(ctx.source_ids)} sources):")
    print(f"    {ctx.text[:200]}...")

    print("\n" + "=" * 70)
    print("  ✅ Phase 11 RAG demo complete")
    print("  Production: swap InMemoryVectorStore for Chroma/Qdrant/Pinecone")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
