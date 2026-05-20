"""ProviderFallbackChain — tries providers in order until one succeeds — P4-T04."""

from __future__ import annotations

from collections.abc import AsyncIterator

from uaaf.observability.cost import Cost
from uaaf_workflow.errors import DegradedError, RetryableError
from uaaf.providers.llm import (
    CompletionRequest,
    Embedding,
    ILLMProvider,
    Response,
    StreamChunk,
)


class ProviderFallbackChain:
    """Tries each provider in order; skips on RetryableError or DegradedError."""

    provider_id = "fallback_chain"

    def __init__(self, providers: list[ILLMProvider]) -> None:
        self._providers = providers

    async def complete(self, request: CompletionRequest) -> Response:
        if not self._providers:
            raise DegradedError("All providers failed: chain is empty")
        last_exc: Exception | None = None
        for provider in self._providers:
            try:
                return await provider.complete(request)
            except (RetryableError, DegradedError) as exc:
                last_exc = exc
        raise DegradedError(f"All providers failed: {last_exc}") from last_exc

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]:
        if not self._providers:
            raise DegradedError("All providers failed: chain is empty")
        return self._providers[0].stream(request)  # type: ignore[return-value]

    async def embed(self, text: str, model: str | None = None) -> Embedding:
        if not self._providers:
            raise DegradedError("All providers failed: chain is empty")
        return await self._providers[0].embed(text, model)

    def estimate_cost(self, request: CompletionRequest) -> Cost:
        if not self._providers:
            return Cost(input_tokens=0, output_tokens=0, usd=0.0, provider="fallback_chain", model=request.model)
        return self._providers[0].estimate_cost(request)
