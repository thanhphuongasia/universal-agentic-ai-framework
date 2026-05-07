"""IKnowledgeBackbone Protocol + shared models — P3-T01."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class BackboneType(StrEnum):
    MEMORY = "memory"
    GRAPH = "graph"
    HYBRID = "hybrid"


@dataclass(frozen=True)
class QueryResult:
    """Results from a backbone query."""

    results: list[str]
    scores: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AssembledContext:
    """Token-budget-trimmed context ready to inject into a prompt."""

    text: str
    token_count: int
    source_ids: list[str] = field(default_factory=list)


@runtime_checkable
class IKnowledgeBackbone(Protocol):
    """Retrieves and assembles context for agent prompts."""

    backbone_type: BackboneType

    async def write(
        self,
        observation: str,
        scope_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> None: ...

    async def query(
        self,
        query: str,
        scope_key: str,
        top_k: int = 5,
    ) -> QueryResult: ...

    async def assemble_context(
        self,
        query: str,
        scope_key: str,
        budget_tokens: int = 2000,
    ) -> AssembledContext: ...
