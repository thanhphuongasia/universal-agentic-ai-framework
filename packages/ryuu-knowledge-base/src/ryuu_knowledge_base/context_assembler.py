from __future__ import annotations

from typing import Any

from ryuu_knowledge_base.backbone import AssembledContext, IKnowledgeBackbone


class ContextAssembler:
    def __init__(self, backbone: IKnowledgeBackbone) -> None:
        self._backbone = backbone

    async def write(
        self,
        observation: str,
        scope_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self._backbone.write(observation, scope_key, metadata)

    async def assemble(
        self,
        query: str,
        scope_key: str,
        budget_tokens: int = 2000,
    ) -> AssembledContext:
        return await self._backbone.assemble_context(query, scope_key, budget_tokens)
