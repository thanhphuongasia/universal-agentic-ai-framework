"""IIntentAnalyzer Protocol — P1-T02."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from uaaf.intent.models import StructuredIntent


@runtime_checkable
class IIntentAnalyzer(Protocol):
    """Converts a raw user message into a StructuredIntent."""

    async def analyze(
        self,
        message: str,
        scope_key: str,
        history: list[dict[str, str]] | None = None,
    ) -> StructuredIntent: ...
