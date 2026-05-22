"""Query decomposition — break a complex user query into independent sub-tasks.

Example: "summarize my unfinished todos and create Anki cards from notes"
decomposes into:
  1. List unfinished todos + summarize
  2. Read recent notes + generate Anki cards

Each sub-task can be dispatched separately (e.g. to different MCP servers)
and results merged.

Two impls:
  • LLMQueryDecomposer       — calls LLM via ILLMProvider + PromptRegistry
  • PatternQueryDecomposer   — regex/keyword-based, no LLM

Prompt template: `ryuu_cognitive/prompts/query_decomposition/v1.yaml`
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ryuu_prompts import PromptRegistry
from ryuu_providers.llm import ILLMProvider


# ---------------------------------------------------------------------------
# Value type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SubQuery:
    """One atomic sub-task extracted from a complex user query."""
    text: str
    intent: str = ""   # optional label: "summarize" | "list" | "create" | ...
    metadata: dict | None = None


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class IQueryDecomposer(Protocol):
    """Strategy for splitting a complex query into atomic sub-queries."""

    max_subqueries: int

    async def decompose(self, query: str) -> list[SubQuery]:
        """Returns a list of sub-queries. If decomposition isn't needed
        (single-task query), returns `[SubQuery(text=query)]`."""
        ...


# ---------------------------------------------------------------------------
# LLMQueryDecomposer — default impl
# ---------------------------------------------------------------------------

@dataclass
class LLMQueryDecomposer:
    """Default IQueryDecomposer — LLM extracts sub-tasks.

    Uses ILLMProvider + PromptRegistry. Prompt template variables:
      • {query}  — the user request
      • {max_n}  — maximum number of sub-tasks allowed
    """

    provider: ILLMProvider
    registry: PromptRegistry
    max_subqueries: int = 5
    project: str = "query_decomposition"
    version: str = "v1"
    prompt_name: str = "decompose"

    async def decompose(self, query: str) -> list[SubQuery]:
        if not query.strip():
            return []
        try:
            cfg = self.registry.load(self.project, self.version)
            request = self.registry.build_request(
                cfg, self.prompt_name, include_tools=False,
                query=query, max_n=self.max_subqueries,
            )
            result = await self.provider.complete(request)
            items = _parse_subquery_array(result.content or "")
        except Exception:  # noqa: BLE001 — never fail parent on decomposition error
            return [SubQuery(text=query)]

        if not items:
            return [SubQuery(text=query)]
        out = [
            SubQuery(text=it["text"], intent=it.get("intent", ""))
            for it in items[: self.max_subqueries]
            if isinstance(it.get("text"), str) and it["text"].strip()
        ]
        return out or [SubQuery(text=query)]


def _parse_subquery_array(response: str) -> list[dict]:
    text = response.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [x for x in parsed if isinstance(x, dict)]


# ---------------------------------------------------------------------------
# PatternQueryDecomposer — no LLM, conjunction-based
# ---------------------------------------------------------------------------

DEFAULT_SPLITTERS = [
    r"\s+and\s+then\s+",
    r"\s*;\s*",
    r"\s+,\s+then\s+",
    r"\s+then\s+",
    r"\s+and\s+also\s+",
    r"\s+plus\s+",
    r"\s+and\s+",
]


@dataclass
class PatternQueryDecomposer:
    """Splits on conjunctions/punctuation. Free, fast, lossy.

    Use when LLM cost matters and queries are simple enough that "X and Y"
    pattern is reliable. Won't catch implicit decomposition like "summarize
    everything from this week" → ["list weekly items", "summarize"].
    """

    splitters: list[str] = field(default_factory=lambda: list(DEFAULT_SPLITTERS))
    max_subqueries: int = 5

    async def decompose(self, query: str) -> list[SubQuery]:
        q = query.strip()
        if not q:
            return []
        parts: list[str] = [q]
        for pattern in self.splitters:
            new_parts: list[str] = []
            for part in parts:
                new_parts.extend(re.split(pattern, part, flags=re.IGNORECASE))
            parts = [p.strip() for p in new_parts if p.strip()]
            if len(parts) >= self.max_subqueries:
                break

        if len(parts) == 1:
            return [SubQuery(text=parts[0])]
        return [SubQuery(text=p) for p in parts[: self.max_subqueries]]
