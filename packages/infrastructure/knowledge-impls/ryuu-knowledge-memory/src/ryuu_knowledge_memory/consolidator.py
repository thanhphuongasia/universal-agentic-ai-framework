"""DreamingConsolidator + EvictionJob — offline memory consolidation.

DreamingConsolidator:
  Runs after a session ends. Clusters unconsolidated episodic entries by
  topic similarity (greedy cosine), summarizes each cluster into one semantic
  fact via LLM, then marks episodic entries as consolidated.

EvictionJob:
  Applies importance-weighted time-decay to episodic entries. Low-scoring
  entries get archived or deleted so episodic memory doesn't grow unbounded.

Both are designed for personal-use scale (~10-50 entries/session). The LLM
and embedder are optional — pass None to skip those steps.

Usage:
    dreamer = DreamingConsolidator(episodic, semantic, llm=provider, embedder=provider)
    await dreamer.run_cycle(scope_key="user123")
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ryuu_knowledge_memory.store import MemoryEntry

if TYPE_CHECKING:
    from ryuu_knowledge_memory.episodic import EpisodicMemoryStore
    from ryuu_knowledge_memory.semantic import SemanticMemoryStore


# ── helpers ─────────────────────────────────────────────────────────────────

def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


_SUMMARIZE_SYSTEM = (
    "You receive a list of related memory observations. "
    "Summarize them into ONE concise fact under 2 sentences. "
    "Keep the most important information. "
    "Return only the fact text — no markdown, no explanation."
)

_EXTRACT_SYSTEM = (
    "Decide if the following observation contains information worth remembering long-term.\n\n"
    "SIGNAL (store): specific facts, preferences, decisions, goals, expertise.\n"
    "NOISE (skip): greetings, filler phrases, thinking-aloud with no conclusion.\n\n"
    "IMPORTANCE:\n"
    "  high   — preferences, expertise, identity, long-term goals\n"
    "  medium — current projects, recent decisions, active context\n"
    "  low    — one-off mentions, temporary states\n\n"
    'Return JSON exactly: {"is_signal": bool, "extracted_fact": "string|null", "importance": "high|medium|low"}'
)


# ── EvictionJob ──────────────────────────────────────────────────────────────

_DECAY_RATE = 0.95       # 5% per idle day
_LOW_THRESHOLD = 0.10    # below 10% → evict candidate
_ARCHIVE_TTL_DAYS = 30   # grace period before hard-delete

_IMPORTANCE_BASE = {"high": 1.0, "medium": 0.6, "low": 0.3}


@dataclass
class EvictionJob:
    """Prune low-value episodic entries using importance-weighted time decay."""

    episodic: EpisodicMemoryStore

    async def run(self, scope_key: str) -> None:
        entries = await self.episodic.get_all_active(scope_key)
        now = time.time()

        for entry in entries:
            if entry.importance == "high":
                continue  # never evict high-importance

            days_idle = (now - entry.created_at) / 86_400
            base = _IMPORTANCE_BASE.get(entry.importance, 0.3)
            decayed = base * (_DECAY_RATE ** days_idle)

            if decayed < _LOW_THRESHOLD:
                if entry.status == "consolidated":
                    await self.episodic.delete(entry.id)
                else:
                    await self.episodic.archive(entry.id, ttl_days=_ARCHIVE_TTL_DAYS)

        await self.episodic.delete_expired_archives(scope_key)


# ── DreamingConsolidator ─────────────────────────────────────────────────────

@dataclass
class DreamingConsolidator:
    """Consolidate episodic memory into semantic memory after a session ends.

    llm and embedder are optional ILLMProvider instances (duck-typed; pass
    any object with async .complete() / async .embed() methods).
    Without an embedder, clustering falls back to sequential grouping.
    Without an llm, entries are stored verbatim (no summarization).
    """

    episodic: EpisodicMemoryStore
    semantic: SemanticMemoryStore
    llm: Any = None       # ILLMProvider | None
    embedder: Any = None  # ILLMProvider | None (same interface, embed() method)

    _eviction: EvictionJob = field(init=False)

    def __post_init__(self) -> None:
        self._eviction = EvictionJob(self.episodic)

    async def run_cycle(self, scope_key: str) -> None:
        await self._eviction.run(scope_key)

        pending = await self.episodic.get_unconsolidated(scope_key, limit=50)
        if not pending:
            return

        clusters = await self._cluster(pending)

        for cluster in clusters:
            if not cluster:
                continue

            if len(cluster) == 1 and cluster[0].importance != "high":
                continue  # skip low-value singletons

            summary = await self._summarize(cluster)
            if not summary:
                continue

            # Dedup against existing semantic entries.
            # Re-use a cluster entry's existing embedding before calling the embedder,
            # so dedup works even when no embedder is configured.
            emb = next((e.embedding for e in cluster if e.embedding), None)
            if emb is None:
                emb = await self._embed(summary)
            if await self._is_duplicate_in_semantic(summary, scope_key, emb):
                await self.episodic.mark_consolidated([e.id for e in cluster])
                continue

            meta: dict[str, Any] = {
                "importance": "high",
                "source_entry_ids": [e.id for e in cluster],
            }
            if emb:
                meta["embedding"] = emb

            await self.semantic.store(summary, scope_key=scope_key, metadata=meta)
            await self.episodic.mark_consolidated([e.id for e in cluster])

    # ── internals ────────────────────────────────────────────────────────────

    async def _embed(self, text: str) -> list[float] | None:
        if self.embedder is None:
            return None
        try:
            result = await self.embedder.embed(text)
            return result.vector if hasattr(result, "vector") else None
        except Exception:
            return None

    async def _cluster(
        self, entries: list[MemoryEntry]
    ) -> list[list[MemoryEntry]]:
        """Greedy cosine clustering; falls back to one-entry-per-cluster."""
        clusters: list[list[MemoryEntry]] = []
        centroids: list[list[float]] = []
        _MERGE_THRESHOLD = 0.75

        for entry in entries:
            emb = entry.embedding or await self._embed(entry.content)
            placed = False
            if emb:
                for i, centroid in enumerate(centroids):
                    if _cosine(emb, centroid) >= _MERGE_THRESHOLD:
                        clusters[i].append(entry)
                        n = len(clusters[i])
                        centroids[i] = [
                            (c * (n - 1) + e) / n for c, e in zip(centroid, emb)
                        ]
                        placed = True
                        break
            if not placed:
                clusters.append([entry])
                centroids.append(emb or [])

        return clusters

    async def _summarize(self, cluster: list[MemoryEntry]) -> str | None:
        if len(cluster) == 1:
            return cluster[0].content

        if self.llm is None:
            # No LLM — concatenate most important entries
            by_importance = sorted(
                cluster,
                key=lambda e: {"high": 0, "medium": 1, "low": 2}.get(e.importance, 1),
            )
            return by_importance[0].content

        combined = "\n".join(f"- {e.content}" for e in cluster)
        try:
            # Import here to avoid hard dep; caller must have ryuu_providers_core installed
            from ryuu_providers_core import CompletionRequest, Message  # type: ignore[import]
            response = await self.llm.complete(CompletionRequest(
                model="claude-haiku-4-5-20251001",
                messages=[Message(role="user", content=combined)],
                system=_SUMMARIZE_SYSTEM,
                max_tokens=150,
                temperature=0,
            ))
            return response.content.strip() or None
        except Exception:
            return cluster[0].content  # fallback

    async def _is_duplicate_in_semantic(
        self, text: str, scope_key: str, emb: list[float] | None
    ) -> bool:
        existing = await self.semantic.retrieve(
            text, scope_key=scope_key, top_k=3, query_embedding=emb
        )
        if not emb:
            return False
        return any(
            e.embedding and _cosine(emb, e.embedding) > 0.92
            for e in existing
        )


# ── ExtractionFilter ─────────────────────────────────────────────────────────

@dataclass
class ExtractionFilter:
    """LLM-based signal/noise filter for episodic writes.

    Usage:
        filt = ExtractionFilter(llm=provider)
        result = await filt.process("Thanks for your help")
        # result.should_store == False
    """

    llm: Any  # ILLMProvider

    async def process(
        self, observation: str
    ) -> tuple[bool, str, str]:
        """Returns (should_store, cleaned_content, importance)."""
        try:
            from ryuu_providers_core import CompletionRequest, Message  # type: ignore[import]
            response = await self.llm.complete(CompletionRequest(
                model="claude-haiku-4-5-20251001",
                messages=[Message(role="user", content=f'Observation: "{observation}"')],
                system=_EXTRACT_SYSTEM,
                max_tokens=100,
                temperature=0,
            ))
            parsed = json.loads(response.content)
        except Exception:
            return True, observation, "medium"  # safe fallback: store as-is

        if not parsed.get("is_signal"):
            return False, observation, "low"

        content = parsed.get("extracted_fact") or observation
        importance = parsed.get("importance", "medium")
        return True, content, importance
