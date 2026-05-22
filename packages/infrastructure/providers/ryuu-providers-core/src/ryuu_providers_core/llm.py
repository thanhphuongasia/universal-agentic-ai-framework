"""ILLMProvider Protocol — the contract all LLM adapters must implement."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ryuu_core.models import Cost


@dataclass
class Message:
    role: str   # "system" | "user" | "assistant" | "tool"
    content: str
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None


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
    response_schema: dict[str, Any] | None = None
    tools: list[dict[str, Any]] | None = None
    system: str | None = None


@runtime_checkable
class ILLMProvider(Protocol):
    """Contract for LLM provider adapters.

    All I/O methods are async.  Providers MUST NOT import asyncio directly;
    the calling framework uses anyio which bridges both asyncio and trio.
    """

    provider_id: str

    async def complete(self, request: CompletionRequest) -> Response: ...

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]: ...

    async def embed(self, text: str, model: str | None = None) -> Embedding: ...

    def estimate_cost(self, request: CompletionRequest) -> Cost: ...
