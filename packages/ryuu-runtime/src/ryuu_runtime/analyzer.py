"""IIntentAnalyzer Protocol."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ryuu_core.models import StructuredIntent


@runtime_checkable
class IIntentAnalyzer(Protocol):
    """Converts a raw user message into a StructuredIntent."""

    async def analyze(
        self,
        message: str,
        scope_key: str,
        history: list[dict[str, str]] | None = None,
    ) -> StructuredIntent: ...
