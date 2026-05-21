"""RAGBackbone — IKnowledgeBackbone impl using RAGPipeline. Phase 11."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ryuu_knowledge_base.backbone import (
    AssembledContext,
    BackboneType,
    IKnowledgeBackbone,
    QueryResult,
)

from ryuu_knowledge_rag.pipeline import RAGPipeline


# RAG isn't memory/graph/hybrid — but IKnowledgeBackbone protocol requires
# one of those enum values. We pick HYBRID since RAG = vector + retrieval
# (composite). Future: extend BackboneType enum with RAG variant.
_RAG_BACKBONE_TYPE = BackboneType.HYBRID


@dataclass
class RAGBackbone:
    """`IKnowledgeBackbone` impl using `RAGPipeline` underneath.

    Pluggable as `Agent(knowledge=RAGBackbone(...))` (Factory integration
    deferred to Phase 11.x; class-based agents accept it via constructor).

    Example::

        backbone = RAGBackbone(pipeline=RAGPipeline(
            embedder=OpenAIProvider(api_key=...),
        ))
        await backbone.write("Python is a programming language", scope_key="docs")
        result = await backbone.query("What is Python?", scope_key="docs", top_k=3)
        # result.results = ["Python is a programming language", ...]
    """

    pipeline: RAGPipeline
    backbone_type: BackboneType = field(default=_RAG_BACKBONE_TYPE)
    # Token cost estimate per char for assemble_context budget trimming.
    # GPT tokenizer averages ~4 chars/token for English.
    _chars_per_token: int = 4

    async def write(
        self,
        observation: str,
        scope_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Ingest a single observation into RAG pipeline."""
        doc = {"text": observation, "metadata": metadata or {}}
        await self.pipeline.ingest(documents=[doc], scope_key=scope_key)

    async def query(
        self,
        query: str,
        scope_key: str,
        top_k: int = 5,
    ) -> QueryResult:
        """Retrieve top-k similar chunks. Filter by scope_key."""
        hits = await self.pipeline.retrieve(query, top_k=top_k, scope_key=scope_key)
        return QueryResult(
            results=[h.record.text for h in hits],
            scores=[h.score for h in hits],
            metadata={"backbone": "rag", "hits_count": len(hits)},
        )

    async def assemble_context(
        self,
        query: str,
        scope_key: str,
        budget_tokens: int = 2000,
    ) -> AssembledContext:
        """Retrieve + concatenate up to `budget_tokens` worth of chunks."""
        # Pull more than needed; trim to budget
        hits = await self.pipeline.retrieve(
            query, top_k=20, scope_key=scope_key,
        )

        budget_chars = budget_tokens * self._chars_per_token
        accumulated: list[str] = []
        source_ids: list[str] = []
        used = 0
        for hit in hits:
            cost = len(hit.record.text)
            if used + cost > budget_chars and accumulated:
                break
            accumulated.append(hit.record.text)
            source_ids.append(hit.record.id)
            used += cost

        text = "\n\n---\n\n".join(accumulated)
        approx_tokens = used // self._chars_per_token
        return AssembledContext(
            text=text,
            token_count=approx_tokens,
            source_ids=source_ids,
        )


__all__ = ["RAGBackbone"]
