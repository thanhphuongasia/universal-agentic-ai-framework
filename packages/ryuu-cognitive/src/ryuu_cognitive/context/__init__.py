"""ryuu_cognitive.context — context-management primitives.

Three families of LLM-driven preprocessing that handlers wire into their flow:

  • compaction — shrink long conversation history without losing meaning
  • query_expansion — generate paraphrases of one query for broader retrieval
  • query_decomposition — split a complex query into atomic sub-tasks

All primitives accept an LLM via an injected
`Callable[[str], Awaitable[str]]` so they're decoupled from any specific
provider. Non-LLM fallbacks (SynonymExpander, PatternQueryDecomposer) are
shipped for use cases where cost matters more than quality.

See `docs/cookbook/` for end-to-end usage examples.
"""

from ryuu_cognitive.context.compaction import (
    CompactionTurn,
    HierarchicalCompactor,
    IConversationCompactor,
    LLMCompactor,
)
from ryuu_cognitive.context.query_decomposition import (
    IQueryDecomposer,
    LLMQueryDecomposer,
    PatternQueryDecomposer,
    SubQuery,
)
from ryuu_cognitive.context.query_expansion import (
    IQueryExpander,
    LLMQueryExpander,
    SynonymExpander,
)

__all__ = [
    # compaction
    "CompactionTurn",
    "HierarchicalCompactor",
    "IConversationCompactor",
    "LLMCompactor",
    # query expansion
    "IQueryExpander",
    "LLMQueryExpander",
    "SynonymExpander",
    # query decomposition
    "IQueryDecomposer",
    "LLMQueryDecomposer",
    "PatternQueryDecomposer",
    "SubQuery",
]
