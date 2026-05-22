"""ryuu_cognitive.recall — composable memory recall pipeline.

Public API:
    RecallPipeline         — runs stages in order; short-circuits if skipped
    IRecallStage           — Protocol for plugging in new stages
    RecallContext          — mutable state passed through stages
    RecallResult           — final output for prompt injection

    Built-in stages (mix-and-match):
        IntentFilterStage      skip chitchat / commands
        ExpansionStage         generate paraphrases
        DecompositionStage     break complex queries into sub-tasks
        MultiQueryRetrievalStage   fan-out backbone queries
        RRFusionStage          Reciprocal Rank Fusion
        TokenBudgetStage       trim to prompt budget

    RecallPipelineBuilder  — convenience factories:
        .naive(backbone)
        .with_expansion(backbone, expander=...)
        .full(backbone, analyzer=..., expander=..., decomposer=...)
"""

from ryuu_cognitive.recall.builders import RecallPipelineBuilder
from ryuu_cognitive.recall.pipeline import (
    IRecallStage,
    RecallContext,
    RecallPipeline,
    RecallResult,
)
from ryuu_cognitive.recall.stages import (
    DecompositionStage,
    ExpansionStage,
    IntentFilterStage,
    MultiQueryRetrievalStage,
    RRFusionStage,
    TokenBudgetStage,
)

__all__ = [
    # Core
    "RecallPipeline",
    "RecallPipelineBuilder",
    "RecallContext",
    "RecallResult",
    "IRecallStage",
    # Stages
    "IntentFilterStage",
    "ExpansionStage",
    "DecompositionStage",
    "MultiQueryRetrievalStage",
    "RRFusionStage",
    "TokenBudgetStage",
]
