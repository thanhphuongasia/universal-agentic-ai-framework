"""Built-in IRecallStage implementations.

Six stages cover the standard pipeline. Mix-and-match via `RecallPipeline.stages`:

  • IntentFilterStage          — skip pipeline for chitchat / commands
  • ExpansionStage             — generate query paraphrases
  • DecompositionStage         — break complex queries into sub-tasks
  • MultiQueryRetrievalStage   — run all queries against the backbone
  • RRFusionStage              — Reciprocal Rank Fusion merge across queries
  • TokenBudgetStage           — trim final list to fit a token budget

Adding a new stage = write a class with `.name` + `async execute(ctx, backbone)`
and append/insert into `pipeline.stages`. No framework code changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ryuu_knowledge_base.backbone import IKnowledgeBackbone

from ryuu_cognitive.recall.pipeline import RecallContext


# ---------------------------------------------------------------------------
# Stage 1 — Intent filter (skip chitchat / commands)
# ---------------------------------------------------------------------------

@dataclass
class IntentFilterStage:
    """Skip recall pipeline when user's query is chitchat / command.

    `analyzer` must have `.analyze(query, scope_key=...) -> StructuredIntent`.
    Compatible with `ryuu_intent.LLMIntentAnalyzer` via duck typing.
    """
    analyzer: Any
    skip_intent_types: tuple[str, ...] = ("chitchat", "command", "greeting")
    name: str = "intent_filter"

    async def execute(
        self,
        ctx: RecallContext,
        *,
        backbone: IKnowledgeBackbone,
    ) -> RecallContext:
        try:
            intent = await self.analyzer.analyze(ctx.original_query, scope_key=ctx.scope_key)
        except Exception as exc:  # noqa: BLE001 — never fail the pipeline on analyzer error
            ctx.debug["intent_filter_error"] = repr(exc)
            return ctx

        ctx.intent = intent
        intent_type = getattr(intent, "intent_type", "")
        if intent_type in self.skip_intent_types:
            ctx.skipped = True
            ctx.skip_reason = f"intent_type={intent_type}"
        return ctx


# ---------------------------------------------------------------------------
# Stage 2 — Query expansion (paraphrases for broader retrieval)
# ---------------------------------------------------------------------------

@dataclass
class ExpansionStage:
    """Generate paraphrases of the user's query. Compatible with
    `ryuu_cognitive.context.LLMQueryExpander` / `SynonymExpander` via duck typing.
    """
    expander: Any
    name: str = "expansion"

    async def execute(
        self,
        ctx: RecallContext,
        *,
        backbone: IKnowledgeBackbone,
    ) -> RecallContext:
        try:
            ctx.queries = await self.expander.expand(ctx.original_query)
        except Exception as exc:  # noqa: BLE001
            ctx.debug["expansion_error"] = repr(exc)
            # Fall through with original query only
        return ctx


# ---------------------------------------------------------------------------
# Stage 3 — Query decomposition (split complex query into sub-tasks)
# ---------------------------------------------------------------------------

@dataclass
class DecompositionStage:
    """Break a complex query into atomic sub-tasks.

    By default only decomposes when `intent.complexity` matches
    `only_if_complexity` (saves cost for simple queries). Set to None to
    always decompose.
    """
    decomposer: Any
    only_if_complexity: str | None = "HIGH"
    name: str = "decomposition"

    async def execute(
        self,
        ctx: RecallContext,
        *,
        backbone: IKnowledgeBackbone,
    ) -> RecallContext:
        # Gate by complexity if intent available
        if self.only_if_complexity is not None and ctx.intent is not None:
            complexity = getattr(ctx.intent, "complexity", None)
            if complexity is not None and str(complexity).upper() != self.only_if_complexity:
                return ctx

        try:
            subs = await self.decomposer.decompose(ctx.original_query)
            # Drop sub-queries that equal the original (no-op decompositions)
            ctx.sub_queries = [
                sq.text for sq in subs
                if getattr(sq, "text", "") and sq.text != ctx.original_query
            ]
        except Exception as exc:  # noqa: BLE001
            ctx.debug["decomposition_error"] = repr(exc)
        return ctx


# ---------------------------------------------------------------------------
# Stage 4 — Multi-query retrieval (fan-out)
# ---------------------------------------------------------------------------

@dataclass
class MultiQueryRetrievalStage:
    """Run all queries (+ sub-queries) against the backbone, collect results.

    Each query produces up to `top_k` results. Results stored per-query in
    `ctx.raw_results` so the fusion stage can score them.
    """
    top_k: int = 5
    name: str = "retrieval"

    async def execute(
        self,
        ctx: RecallContext,
        *,
        backbone: IKnowledgeBackbone,
    ) -> RecallContext:
        all_queries = (ctx.queries or [ctx.original_query]) + ctx.sub_queries
        seen_queries: set[str] = set()
        deduped_queries = []
        for q in all_queries:
            key = q.strip().lower()
            if key and key not in seen_queries:
                seen_queries.add(key)
                deduped_queries.append(q)

        for q in deduped_queries:
            try:
                result = await backbone.query(q, scope_key=ctx.scope_key, top_k=self.top_k)
                ctx.raw_results.append(list(result.results))
            except Exception as exc:  # noqa: BLE001
                ctx.debug.setdefault("retrieval_errors", []).append(repr(exc))
                ctx.raw_results.append([])
        return ctx


# ---------------------------------------------------------------------------
# Stage 5 — Reciprocal Rank Fusion (industry standard for multi-query)
# ---------------------------------------------------------------------------

@dataclass
class RRFusionStage:
    """Merge per-query result lists via Reciprocal Rank Fusion.

    score(item) = sum over query-lists of 1 / (k + rank_in_that_list)

    k=60 is the standard from the original RRF paper (Cormack et al.) — used
    by Anthropic, Cohere, OpenAI for hybrid retrieval. Higher k → more weight
    to deep ranks; lower k → top results dominate.
    """
    k: int = 60
    name: str = "rrf_fusion"

    async def execute(
        self,
        ctx: RecallContext,
        *,
        backbone: IKnowledgeBackbone,
    ) -> RecallContext:
        if not ctx.raw_results:
            return ctx

        scores: dict[str, float] = {}
        for results in ctx.raw_results:
            for rank, item in enumerate(results, start=1):
                scores[item] = scores.get(item, 0.0) + 1.0 / (self.k + rank)

        ctx.fused_results = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
        ctx.debug["rrf_scores"] = {k: round(v, 4) for k, v in scores.items()}
        return ctx


# ---------------------------------------------------------------------------
# Stage 6 — Token budget (trim final list to fit prompt budget)
# ---------------------------------------------------------------------------

@dataclass
class TokenBudgetStage:
    """Trim the final ranked list to fit a token budget.

    Token estimation is rough (`len(text.split()) * 4 / 3`). For exact
    counting, swap with a tiktoken-backed stage.
    """
    budget_tokens: int = 2000
    name: str = "token_budget"

    async def execute(
        self,
        ctx: RecallContext,
        *,
        backbone: IKnowledgeBackbone,
    ) -> RecallContext:
        source = ctx.fused_results if ctx.fused_results else self._flatten_raw(ctx.raw_results)

        kept: list[str] = []
        used = 0
        for item in source:
            est = len(item.split()) * 4 // 3
            if used + est > self.budget_tokens:
                break
            kept.append(item)
            used += est

        ctx.fused_results = kept
        ctx.debug["budget_tokens_used"] = used
        return ctx

    @staticmethod
    def _flatten_raw(raw_results: list[list[str]]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for rlist in raw_results:
            for it in rlist:
                if it not in seen:
                    seen.add(it)
                    out.append(it)
        return out


__all__ = [
    "DecompositionStage",
    "ExpansionStage",
    "IntentFilterStage",
    "MultiQueryRetrievalStage",
    "RRFusionStage",
    "TokenBudgetStage",
]
