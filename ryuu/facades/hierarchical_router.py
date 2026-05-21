"""HierarchicalRouter — 2-stage routing: category → specific intent (Phase 14.4)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ryuu.facades._helpers import run_step


@dataclass
class HierarchicalRouter:
    """2-stage routing: category → specific intent within category.

    Stage 1: `category_classifier` Agent classifies input → category key
    Stage 2: pick specific intent within `routes_by_category[category]`
             - Default: build inline LLM classifier over options
             - Custom: pass `specific_analyzer(input, options) -> intent_key`

    Fallback: if Stage 1 returns unknown category, use `fallback_route` agent
              if provided, else raise KeyError.

    Pattern #9 from Claude-like Thinking Engine. Routing concern (đi đâu),
    KHÔNG phải cognitive (nghĩ như nào). Lives in facades, not strategies.

    Example:
        router = HierarchicalRouter(
            category_classifier=Agent(model="gpt-4o-mini",
                instructions="Pick category: structure | behavior | data"),
            routes_by_category={
                "structure": {"symbol_explain": s_agent, "dep_analysis": d_agent},
                "behavior":  {"sequence_diagram": seq_agent},
                "data":      {"crud_matrix": crud_agent, "entity_diagram": e_agent},
            },
            fallback_route=symbol_agent,
        )
        result = await router.run(query)
    """

    category_classifier: Any   # Agent (Stage 1)
    routes_by_category: dict[str, dict[str, Any]]
    fallback_route: Any | None = None   # Agent or facade with .run()
    specific_analyzer: Callable[[Any, list[str]], str | Awaitable[str]] | None = None

    def __post_init__(self) -> None:
        if not self.routes_by_category:
            raise ValueError("HierarchicalRouter requires non-empty `routes_by_category`")

    async def run(self, input_value: Any) -> Any:
        # Stage 1: classify category
        cat_result = await self.category_classifier.run(str(input_value))
        category = str(cat_result.output).strip().lower()

        options_dict = self.routes_by_category.get(category)
        if options_dict is None:
            if self.fallback_route is not None:
                return await run_step(self.fallback_route, input_value)
            raise KeyError(
                f"HierarchicalRouter: category {category!r} not in routes_by_category "
                f"and no `fallback_route` set."
            )

        # Stage 2: pick specific intent
        options = list(options_dict)
        if self.specific_analyzer is not None:
            picked = self.specific_analyzer(input_value, options)
            if hasattr(picked, "__await__"):
                picked = await picked   # type: ignore[misc]
            intent_key = str(picked).strip()
        else:
            intent_key = await self._llm_pick(str(input_value), options)

        target = options_dict.get(intent_key) or options_dict[options[0]]
        return await run_step(target, input_value)

    async def _llm_pick(self, query: str, options: list[str]) -> str:
        """Default Stage-2 picker: reuse category_classifier's model (cost-efficient)."""
        from ryuu.factory import Agent

        picker = Agent(
            model=self.category_classifier.model,
            instructions=(
                f"Pick ONE intent from: {', '.join(options)}. "
                f"Output ONLY the chosen word, no prose."
            ),
            max_tokens=10,
            temperature=0,
        )
        # Share underlying LLM provider (FakeLLM in tests)
        picker._agent.llm = self.category_classifier._agent.llm
        result = await picker.run(query)
        return str(result.output).strip()
