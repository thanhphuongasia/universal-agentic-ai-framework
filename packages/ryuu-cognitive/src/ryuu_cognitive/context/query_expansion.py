"""Query expansion — rewrite one query into multiple variants for better retrieval.

When the user asks "tell me about my Tokyo trip", a single search may miss
memories tagged "Japan visit" or "vacation east asia". An expander generates
paraphrases that are run independently and merged.

Two impls:
  • LLMQueryExpander    — calls an LLM via ILLMProvider + PromptRegistry
  • SynonymExpander     — dict-based synonym substitution (no LLM, fast, free)

Prompt template: `ryuu_cognitive/prompts/query_expansion/v1.yaml`
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ryuu_prompts import PromptRegistry
from ryuu_providers.llm import ILLMProvider


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class IQueryExpander(Protocol):
    """Strategy for generating multiple query variants from one input query."""

    num_variants: int

    async def expand(self, query: str) -> list[str]:
        """Returns a list of queries INCLUDING the original. Length ≤ num_variants+1.

        The original is always first — if the LLM/expansion fails, callers
        still get a usable list of [original].
        """
        ...


# ---------------------------------------------------------------------------
# LLMQueryExpander — default impl
# ---------------------------------------------------------------------------

@dataclass
class LLMQueryExpander:
    """Generate paraphrases via an LLM call.

    Uses ILLMProvider + PromptRegistry. Prompt template available variables:
      • {query} — the original user query
      • {n}     — desired number of variants
    """

    provider: ILLMProvider
    registry: PromptRegistry
    num_variants: int = 3
    project: str = "query_expansion"
    version: str = "v1"
    prompt_name: str = "expand"

    async def expand(self, query: str) -> list[str]:
        if not query.strip():
            return [query]

        try:
            cfg = self.registry.load(self.project, self.version)
            request = self.registry.build_request(
                cfg, self.prompt_name, include_tools=False,
                query=query, n=self.num_variants,
            )
            result = await self.provider.complete(request)
            variants = _parse_json_array(result.content or "")
        except Exception:  # noqa: BLE001 — never fail the parent flow on expansion error
            return [query]

        # Always include the original, dedupe (case-insensitive), preserve order
        seen: set[str] = set()
        out: list[str] = []
        for q in [query, *variants]:
            key = q.strip().lower()
            if key and key not in seen:
                seen.add(key)
                out.append(q.strip())
        return out[: self.num_variants + 1]


def _parse_json_array(response: str) -> list[str]:
    """Tolerant JSON-array extraction — handles LLM wrap quirks like ```json ... ```."""
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
    return [str(x).strip() for x in parsed if str(x).strip()]


# ---------------------------------------------------------------------------
# SynonymExpander — no LLM, dict-based
# ---------------------------------------------------------------------------

DEFAULT_SYNONYMS: dict[str, list[str]] = {
    "task": ["todo", "item", "action"],
    "todo": ["task", "item"],
    "trip": ["travel", "journey", "vacation"],
    "buy": ["purchase", "get", "acquire"],
}


@dataclass
class SynonymExpander:
    """Generate variants by substituting one synonym at a time.

    Cheap and predictable — no LLM call. Output quality bounded by the
    synonym dict, but useful as a free baseline or fallback.
    """

    synonyms: dict[str, list[str]] = field(default_factory=lambda: dict(DEFAULT_SYNONYMS))
    num_variants: int = 3

    async def expand(self, query: str) -> list[str]:
        if not query.strip():
            return [query]
        tokens = query.split()
        variants: list[str] = [query]
        seen: set[str] = {query.lower()}

        for i, tok in enumerate(tokens):
            lower = tok.lower().strip(".,!?")
            alts = self.synonyms.get(lower, [])
            for alt in alts:
                new_tokens = list(tokens)
                new_tokens[i] = alt.title() if tok[:1].isupper() else alt
                variant = " ".join(new_tokens)
                key = variant.lower()
                if key in seen:
                    continue
                seen.add(key)
                variants.append(variant)
                if len(variants) >= self.num_variants + 1:
                    return variants
        return variants
