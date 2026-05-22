"""RecallPipelineBuilder — convenience factories for common compositions.

Not required to use the pipeline — `RecallPipeline(stages=[...])` works
fine. These builders just save users from remembering the correct stage
order + defaults for common scenarios.
"""

from __future__ import annotations

from typing import Any

from ryuu_knowledge_base.backbone import IKnowledgeBackbone

from ryuu_cognitive.recall.pipeline import RecallPipeline
from ryuu_cognitive.recall.stages import (
    DecompositionStage,
    ExpansionStage,
    IntentFilterStage,
    MultiQueryRetrievalStage,
    RRFusionStage,
    TokenBudgetStage,
)


class RecallPipelineBuilder:
    """Three pre-baked compositions for common cost/quality tradeoffs.

    For anything else, instantiate `RecallPipeline(stages=[...])` directly.
    """

    @classmethod
    def naive(
        cls,
        backbone: IKnowledgeBackbone,
        *,
        top_k: int = 5,
        budget_tokens: int = 2000,
    ) -> RecallPipeline:
        """Simplest — single retrieval + budget. No preprocessing.

        Use when: latency budget tight, no LLM cost to spare, simple queries.
        """
        return RecallPipeline(
            backbone=backbone,
            stages=[
                MultiQueryRetrievalStage(top_k=top_k),
                TokenBudgetStage(budget_tokens=budget_tokens),
            ],
        )

    @classmethod
    def with_expansion(
        cls,
        backbone: IKnowledgeBackbone,
        *,
        expander: Any,
        top_k: int = 5,
        budget_tokens: int = 2000,
    ) -> RecallPipeline:
        """Add query expansion (paraphrases) + RRF fusion.

        Use when: free-form questions where paraphrasing helps recall.
        Cheap if expander is SynonymExpander (no LLM); +500ms if LLMQueryExpander.
        """
        return RecallPipeline(
            backbone=backbone,
            stages=[
                ExpansionStage(expander=expander),
                MultiQueryRetrievalStage(top_k=top_k),
                RRFusionStage(),
                TokenBudgetStage(budget_tokens=budget_tokens),
            ],
        )

    @classmethod
    def full(
        cls,
        backbone: IKnowledgeBackbone,
        *,
        analyzer: Any,
        expander: Any,
        decomposer: Any,
        top_k: int = 5,
        budget_tokens: int = 2000,
        skip_intent_types: tuple[str, ...] = ("chitchat", "command", "greeting"),
        decompose_complexity: str | None = "HIGH",
    ) -> RecallPipeline:
        """All 5 stages — analyzer (skip chitchat) + expand + decompose + retrieve + RRF + budget.

        Use when: production personal assistant where recall quality matters
        more than latency / cost. Saves on overall LLM cost (chitchat skips
        retrieval entirely).
        """
        return RecallPipeline(
            backbone=backbone,
            stages=[
                IntentFilterStage(
                    analyzer=analyzer,
                    skip_intent_types=skip_intent_types,
                ),
                ExpansionStage(expander=expander),
                DecompositionStage(
                    decomposer=decomposer,
                    only_if_complexity=decompose_complexity,
                ),
                MultiQueryRetrievalStage(top_k=top_k),
                RRFusionStage(),
                TokenBudgetStage(budget_tokens=budget_tokens),
            ],
        )


__all__ = ["RecallPipelineBuilder"]
