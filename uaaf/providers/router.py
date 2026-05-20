"""ModelRouter — routes LLM calls by ModelTier with per-provider CircuitBreakers — P4-T02+T03."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from uaaf.intent.models import ModelTier
from uaaf.observability.cost import Cost
from uaaf_workflow.errors import DegradedError
from uaaf.providers.circuit_breaker import CircuitBreaker
from uaaf.providers.llm import (
    CompletionRequest,
    Embedding,
    ILLMProvider,
    Response,
    StreamChunk,
)


class ModelRouter:
    """Routes requests to providers by model tier; trips circuit breakers on failure."""

    provider_id = "router"

    def __init__(
        self,
        providers: dict[ModelTier, ILLMProvider],
        fallback: ILLMProvider | None = None,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
    ) -> None:
        self._providers = providers
        self._fallback = fallback
        self._breakers: dict[str, CircuitBreaker] = {
            p.provider_id: CircuitBreaker(failure_threshold, recovery_timeout)
            for p in providers.values()
        }

    # ------------------------------------------------------------------
    # Public routing API
    # ------------------------------------------------------------------

    def route(self, model_tier: ModelTier) -> ILLMProvider:
        """Return an available provider for the given tier, or fallback."""
        provider = self._providers.get(model_tier)
        if provider is not None:
            breaker = self._breakers.get(provider.provider_id)
            if breaker is None or breaker.is_available():
                return provider
        if self._fallback is not None:
            return self._fallback
        raise DegradedError(f"No available provider for tier {model_tier!r} and no fallback configured")

    def record_failure(self, provider_id: str) -> None:
        if provider_id in self._breakers:
            self._breakers[provider_id].record_failure()

    def record_success(self, provider_id: str) -> None:
        if provider_id in self._breakers:
            self._breakers[provider_id].record_success()

    # ------------------------------------------------------------------
    # ILLMProvider implementation
    # ------------------------------------------------------------------

    async def complete(self, request: CompletionRequest) -> Response:
        tier = self._model_to_tier(request.model)
        provider = self._get_provider_with_fallback(tier)
        try:
            response = await provider.complete(request)
            self.record_success(provider.provider_id)
            return response
        except Exception as exc:
            self.record_failure(provider.provider_id)
            if self._fallback is not None and provider is not self._fallback:
                return await self._fallback.complete(request)
            raise DegradedError(f"Provider {provider.provider_id!r} failed: {exc}") from exc

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]:
        tier = self._model_to_tier(request.model)
        provider = self._get_provider_with_fallback(tier)
        return provider.stream(request)  # type: ignore[return-value]

    async def embed(self, text: str, model: str | None = None) -> Embedding:
        # Use STANDARD tier for embeddings
        provider = self._get_provider_with_fallback(ModelTier.STANDARD)
        return await provider.embed(text, model)

    def estimate_cost(self, request: CompletionRequest) -> Cost:
        tier = self._model_to_tier(request.model)
        try:
            provider = self._get_provider_with_fallback(tier)
            return provider.estimate_cost(request)
        except DegradedError:
            return Cost(input_tokens=0, output_tokens=0, usd=0.0, provider="router", model=request.model)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_provider_with_fallback(self, tier: ModelTier) -> ILLMProvider:
        return self.route(tier)

    def _model_to_tier(self, model: str) -> ModelTier:
        lower = model.lower()
        # Direct tier string from LLMAgent.select_model() — "cheap"/"standard"/"powerful"
        try:
            return ModelTier(lower)
        except ValueError:
            pass
        # Model-name heuristics (backward compat)
        if "mini" in lower or "haiku" in lower:
            return ModelTier.CHEAP
        if "opus" in lower:
            return ModelTier.POWERFUL
        return ModelTier.STANDARD

    # Make router itself satisfy duck-typed Any check
    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)
