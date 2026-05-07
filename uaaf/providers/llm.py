"""ILLMProvider Protocol — the contract all LLM adapters must implement.

T07 deliverable: Protocol + dataclasses.  Adapters live in uaaf/providers/adapters/.
Contract tests live in tests/contract/test_llm_provider_contract.py.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from uaaf.observability.cost import Cost

# ---------------------------------------------------------------------------
# Request / response dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Message:
    role: str   # "system" | "user" | "assistant" | "tool"
    content: str
    tool_calls: list[dict[str, Any]] | None = None   # assistant → function-calling
    tool_call_id: str | None = None                  # tool → which call this answers


@dataclass
class TokenUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class Response:
    content: str
    model: str
    usage: TokenUsage
    finish_reason: str = "stop"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class StreamChunk:
    content: str
    is_final: bool = False
    usage: TokenUsage | None = None


@dataclass
class Embedding:
    vector: list[float]
    model: str


@dataclass
class CompletionRequest:
    messages: list[Message]
    model: str
    max_tokens: int = 1024
    temperature: float = 0.0
    response_schema: dict[str, Any] | None = None   # JSON schema for structured output
    tools: list[dict[str, Any]] | None = None
    system: str | None = None


# ---------------------------------------------------------------------------
# ILLMProvider Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ILLMProvider(Protocol):
    """Contract for LLM provider adapters.

    All I/O methods are async.  Providers MUST NOT import asyncio directly;
    the calling framework uses anyio which bridges both asyncio and trio.
    """

    provider_id: str

    async def complete(self, request: CompletionRequest) -> Response:
        """Single-shot completion.  Returns when the full response is ready."""
        ...

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]:
        """Streaming completion.  Caller iterates chunks until ``is_final=True``."""
        ...

    async def embed(self, text: str, model: str | None = None) -> Embedding:
        """Embed *text* using an embedding model."""
        ...

    def estimate_cost(self, request: CompletionRequest) -> Cost:
        """Return an *estimated* cost before making the actual call.

        Used by CostTracker.enforce() to enforce budgets pre-call.
        """
        ...
