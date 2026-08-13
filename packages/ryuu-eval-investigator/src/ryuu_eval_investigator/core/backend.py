"""InvestigatorBackend Protocol — the swap point.

Implementations (in `backends/`) wrap a specific LLM SDK:
    - claude-agent-sdk
    - direct Anthropic SDK
    - ryuu framework
    - any future provider

Core never imports a backend; the domain plugin chooses one.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .models import InputBundle, RootCauseReport


@runtime_checkable
class InvestigatorBackend(Protocol):
    """One investigation = one call. Backend lo loop/tools/streaming."""

    async def investigate(
        self,
        bundle: InputBundle,
        system_prompt: str,
        **kwargs: Any,
    ) -> RootCauseReport:
        """Run investigation. Blocking until report ready.

        Streaming output (if backend supports it) should be handled internally
        — e.g. callback hook or queue. Core consumers only need the final report.
        """
        ...
