"""Anthropic ILLMProvider adapter — T10.

Wraps ``anthropic.AsyncAnthropic`` and maps responses/errors to UAAF types.
Structured output uses the tool-use pattern (Anthropic lacks direct JSON mode).
Install with: ``pip install "uaaf[anthropic]"``
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from uaaf.observability._pricing import calculate_usd
from uaaf.observability.cost import Cost
from uaaf.observability.errors import classify_external_error
from uaaf.providers.llm import (
    CompletionRequest,
    Embedding,
    Response,
    StreamChunk,
    TokenUsage,
)

try:
    from anthropic import AsyncAnthropic
except ImportError:  # pragma: no cover
    AsyncAnthropic = None  # type: ignore[assignment,misc]

_STRUCTURED_TOOL_NAME = "structured_output"


class AnthropicProvider:
    """ILLMProvider backed by the Anthropic API."""

    provider_id = "anthropic"

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str = "claude-haiku-4-5",
        **client_kwargs: Any,
    ) -> None:
        if AsyncAnthropic is None:  # pragma: no cover
            raise ImportError('Install anthropic: pip install "uaaf[anthropic]"')

        self._client = AsyncAnthropic(api_key=api_key, **client_kwargs)
        self._default_model = default_model

    async def complete(self, request: CompletionRequest) -> Response:
        model = request.model or self._default_model
        messages = [{"role": m.role, "content": m.content} for m in request.messages]
        system = request.system or ""

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": request.max_tokens,
        }
        if system:
            kwargs["system"] = system

        # Structured output via tool_use pattern.
        if request.response_schema:
            kwargs["tools"] = [
                {
                    "name": _STRUCTURED_TOOL_NAME,
                    "description": "Return structured output matching the schema.",
                    "input_schema": request.response_schema,
                }
            ]
            kwargs["tool_choice"] = {"type": "tool", "name": _STRUCTURED_TOOL_NAME}
        elif request.tools:
            kwargs["tools"] = request.tools

        try:
            resp = await self._client.messages.create(**kwargs)
        except Exception as exc:
            raise classify_external_error(exc) from exc

        # Extract content blocks — Claude emits text + tool_use in same response.
        content_text = ""
        metadata: dict[str, Any] = {}
        tool_calls = []

        for block in resp.content:
            if block.type == "text":
                content_text = block.text
            elif block.type == "tool_use":
                if block.name == _STRUCTURED_TOOL_NAME:
                    # Structured output pattern — serialize to JSON string.
                    content_text = json.dumps(block.input)
                else:
                    # Regular tool call — map to UAAF format.
                    tool_calls.append({
                        "id": block.id,
                        "function": {
                            "name": block.name,
                            "arguments": block.input,  # already a dict
                        },
                    })

        if tool_calls:
            metadata["tool_calls"] = tool_calls

        usage = resp.usage
        return Response(
            content=content_text,
            model=model,
            usage=TokenUsage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
            ),
            finish_reason=resp.stop_reason or "end_turn",
            metadata=metadata,
        )

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]:
        model = request.model or self._default_model
        messages = [{"role": m.role, "content": m.content} for m in request.messages]

        try:
            async with self._client.messages.stream(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                max_tokens=request.max_tokens,
                system=request.system or "",
            ) as stream:
                async for text in stream.text_stream:
                    yield StreamChunk(content=text, is_final=False)
                final = await stream.get_final_message()
                yield StreamChunk(
                    content="",
                    is_final=True,
                    usage=TokenUsage(
                        input_tokens=final.usage.input_tokens,
                        output_tokens=final.usage.output_tokens,
                    ),
                )
        except Exception as exc:
            raise classify_external_error(exc) from exc

    async def embed(self, text: str, model: str | None = None) -> Embedding:
        raise NotImplementedError(
            "Anthropic does not provide a public embedding endpoint. "
            "Use OpenAIProvider for embeddings."
        )

    def estimate_cost(self, request: CompletionRequest) -> Cost:
        model = request.model or self._default_model
        input_est = sum(len(m.content.split()) * 4 // 3 for m in request.messages)
        output_est = request.max_tokens
        usd = calculate_usd(model, input_est, output_est)
        return Cost(
            input_tokens=input_est,
            output_tokens=output_est,
            usd=usd,
            provider=self.provider_id,
            model=model,
        )

    async def close(self) -> None:
        await self._client.close()
