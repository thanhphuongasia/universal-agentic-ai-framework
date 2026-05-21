"""Phase 11.x — Agent + RAGBackbone integration demo.

Shows `Agent(knowledge=RAGBackbone(...))` automatic context injection on each `.run()`.

Run:
    OPENAI_API_KEY=sk-... python -m examples.rag_agent_demo    # real
    python -m examples.rag_agent_demo                            # FakeLLM
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from dataclasses import dataclass

from ryuu import Agent
from ryuu._testing.fakes import FakeLLMProvider
from ryuu.providers.llm import Response, TokenUsage
from ryuu_knowledge_rag import RAGBackbone, RAGPipeline, RecursiveChunker


# ----------------------------------------------------------------------------
# Mocks — FakeEmbedder + FakeLLM for offline demo
# ----------------------------------------------------------------------------


@dataclass
class _FakeEmbedder:
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


# ----------------------------------------------------------------------------
# Knowledge base for demo
# ----------------------------------------------------------------------------


COMPANY_DOCS = [
    "Our company uses Python 3.11 as the primary language for all backend services.",
    "Tech stack: FastAPI for APIs, PostgreSQL for transactional data, Redis for caching.",
    "Deployment uses Docker + Kubernetes on AWS EKS, with GitHub Actions for CI/CD.",
    "Code review policy: every PR needs 2 approvals before merging to main branch.",
    "Security: all secrets stored in AWS Secrets Manager, never in env files.",
]


async def main() -> None:
    has_key = bool(os.getenv("OPENAI_API_KEY"))
    print("=" * 72)
    print(f"  Phase 11.x — Agent + RAGBackbone Integration Demo")
    print(f"  Mode: {'OpenAI (real)' if has_key else 'FakeLLM (demo)'}")
    print("=" * 72)

    # ── 1. Build RAG backbone + ingest company docs ─────────────────────
    backbone = RAGBackbone(
        pipeline=RAGPipeline(
            embedder=_FakeEmbedder(),
            chunker=RecursiveChunker(chunk_size=200, overlap=30),
        ),
    )
    for doc in COMPANY_DOCS:
        await backbone.write(doc, scope_key="engineering")

    print(f"\n[1] Ingested {len(COMPANY_DOCS)} company docs into RAG backbone")

    # ── 2. Create Agent with knowledge= ──────────────────────────────────
    agent = Agent(
        model="gpt-4o-mini",
        instructions=(
            "You are an internal company assistant. Answer based on retrieved "
            "context. If context doesn't cover the question, say so honestly."
        ),
        knowledge=backbone,                       # ← Phase 11.x integration
        knowledge_budget_tokens=200,              # ~50-100 tokens per chunk
        knowledge_scope_field="domain",           # scope_key from ContextScope.domain
    )

    # Mock LLM for offline demo
    if not has_key:
        agent._agent.llm = FakeLLMProvider(responses=[
            Response(
                content="Based on context: Python 3.11 is the primary backend language.",
                model="fake",
                usage=TokenUsage(input_tokens=50, output_tokens=20),
                finish_reason="stop",
            ),
        ] * 3)

    # ── 3. Run queries — Factory auto-injects RAG context ───────────────
    queries = [
        "What programming language does the company use?",
        "What's the deployment infrastructure?",
        "What's the PR review policy?",
    ]

    print("\n[2] Running queries (Factory auto-injects RAG context):")
    for q in queries:
        print(f"\n  Q: {q}")
        result = await agent.run(q, domain="engineering")
        print(f"  A: {result.output}")

    # ── 4. Demonstrate scope isolation ──────────────────────────────────
    print("\n[3] Scope isolation — different domain → empty context:")
    if not has_key:
        agent._agent.llm = FakeLLMProvider(responses=[Response(
            content="I don't have context about that.",
            model="fake",
            usage=TokenUsage(input_tokens=10, output_tokens=5),
            finish_reason="stop",
        )])
    result = await agent.run("What is Python?", domain="hr")   # wrong scope
    print(f"  Q: What is Python? (scope=hr, not engineering)")
    print(f"  A: {result.output}")

    print("\n" + "=" * 72)
    print("  ✅ Phase 11.x Agent + RAG integration verified")
    print("  Consumer: 1 kwarg `knowledge=backbone` — auto-injection per .run()")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())
