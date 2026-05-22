"""RecallPipeline — composable memory retrieval orchestration.

Pattern: middleware chain. Each stage implements `IRecallStage` and reads/
mutates a shared `RecallContext`. Adding a new stage = define a class and
insert into pipeline.stages. ZERO framework changes.

Why this pattern (Open/Closed Principle):
  • Fixed slots (analyzer=X, expander=Y, decomposer=Z) → adding new kind
    of stage forces RecallPipeline modification → breaking change.
  • Chain pattern → users compose freely. Match LangChain Runnables,
    LlamaIndex QueryPipeline, Express middleware, Django middleware.

Stages share `RecallContext` (mutable). Each stage reads what came before
and may set:
  • ctx.queries          → list of search queries (expansion adds here)
  • ctx.sub_queries      → decomposed sub-tasks
  • ctx.intent           → result of intent analysis
  • ctx.raw_results      → per-query result lists from backbone
  • ctx.fused_results    → merged final ranking
  • ctx.skipped + reason → if true, pipeline short-circuits
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ryuu_knowledge_base.backbone import IKnowledgeBackbone


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------

@dataclass
class RecallContext:
    """Mutable state passed through the pipeline. Each stage may read or
    mutate fields below. Pipeline runner uses `skipped=True` to short-circuit.
    """
    original_query: str
    scope_key: str

    # Filled by stages — empty by default
    queries: list[str] = field(default_factory=list)
    sub_queries: list[str] = field(default_factory=list)
    intent: Any | None = None
    raw_results: list[list[str]] = field(default_factory=list)
    fused_results: list[str] = field(default_factory=list)

    # Control flow
    skipped: bool = False
    skip_reason: str = ""

    # Debug + metadata
    debug: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RecallResult:
    """Final output. Consumer feeds `text` into the LLM prompt."""
    text: str                             # newline-joined items, ready to prompt
    items: list[str]                      # raw items list (post-fusion + budget)
    token_count: int                      # rough estimate (used for budget)
    skipped: bool = False
    skip_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Stage Protocol — every plug-in implements this
# ---------------------------------------------------------------------------

@runtime_checkable
class IRecallStage(Protocol):
    """Pluggable pipeline stage. Implement `name` + `execute()`.

    Stages SHOULD be idempotent (callable multiple times produces same result
    given same input) and SHOULD NOT raise on missing input — return ctx
    unchanged when not applicable.
    """
    name: str

    async def execute(
        self,
        ctx: RecallContext,
        *,
        backbone: IKnowledgeBackbone,
    ) -> RecallContext:
        ...


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

@dataclass
class RecallPipeline:
    """Composable recall pipeline. Stages run in order; short-circuits if
    any stage sets `ctx.skipped=True`.
    """
    backbone: IKnowledgeBackbone
    stages: list[IRecallStage] = field(default_factory=list)
    item_separator: str = "\n  • "
    item_prefix: str = "  • "

    async def recall(self, query: str, scope_key: str) -> RecallResult:
        ctx = RecallContext(
            original_query=query,
            scope_key=scope_key,
            queries=[query],   # seed with original; expansion may extend
        )

        for stage in self.stages:
            ctx = await stage.execute(ctx, backbone=self.backbone)
            if ctx.skipped:
                break

        return self._materialize(ctx)

    def _materialize(self, ctx: RecallContext) -> RecallResult:
        # Prefer fused (post-RRF/budget) if available, else raw concatenation
        if ctx.fused_results:
            items = ctx.fused_results
        elif ctx.raw_results:
            seen: set[str] = set()
            items = []
            for rlist in ctx.raw_results:
                for it in rlist:
                    if it not in seen:
                        seen.add(it)
                        items.append(it)
        else:
            items = []

        if items:
            text = self.item_prefix + self.item_separator.join(items)[len(self.item_separator):] if items else ""
            # Cleaner: just join with newline+bullet
            text = "\n".join(f"  • {it}" for it in items)
        else:
            text = ""

        # Rough token estimate (word count * 1.33)
        token_count = sum(len(it.split()) for it in items) * 4 // 3

        return RecallResult(
            text=text,
            items=items,
            token_count=token_count,
            skipped=ctx.skipped,
            skip_reason=ctx.skip_reason,
            metadata={
                "queries": ctx.queries,
                "sub_queries": ctx.sub_queries,
                "intent": ctx.intent,
                "matches_per_query": [len(r) for r in ctx.raw_results],
                **ctx.debug,
            },
        )
