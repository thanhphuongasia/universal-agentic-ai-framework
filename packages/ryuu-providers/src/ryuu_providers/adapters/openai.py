"""OpenAI ILLMProvider adapter.

Wraps ``openai.AsyncOpenAI`` and maps its responses/errors to RYUU types.
Install with: ``pip install "ryuu-providers[openai]"``
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from ryuu_core.errors import classify_external_error
from ryuu_core.models import Cost

from ryuu_providers._pricing import calculate_usd
from ryuu_providers.llm import (
    CompletionRequest,
    Embedding,
    Message,
    Response,
    StreamChunk,
    TokenUsage,
)

try:
    from openai import AsyncOpenAI
except ImportError:  # pragma: no cover
    AsyncOpenAI = None  # type: ignore[assignment,misc]


# Phase 11.y — OpenAI models supporting strict JSON Schema mode.
# gpt-4o, gpt-4o-mini, o1, o3 series. Older models (gpt-3.5, gpt-4 base)
# fall back to basic `response_format={"type": "json_object"}`.
_STRICT_SCHEMA_PREFIXES = ("gpt-4o", "gpt-5", "o1", "o3", "o4")


def _supports_strict_schema(model: str) -> bool:
    """Detect if model supports `response_format={"type": "json_schema", ...}`."""
    return any(model.startswith(prefix) for prefix in _STRICT_SCHEMA_PREFIXES)


class OpenAIProvider:
    """ILLMProvider backed by the OpenAI API."""

    provider_id = "openai"

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str = "gpt-4o-mini",
        base_url: str | None = None,
        **client_kwargs: Any,
    ) -> None:
        if AsyncOpenAI is None:  # pragma: no cover
            raise ImportError('Install openai: pip install "ryuu-providers[openai]"')

        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            **client_kwargs,
        )
        self._default_model = default_model

    @staticmethod
    def _serialize_message(m: Message) -> dict[str, Any]:
        import json as _json
        d: dict[str, Any] = {"role": m.role, "content": m.content or ""}
        if m.tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["function"]["name"],
                        "arguments": _json.dumps(tc["function"]["arguments"]),
                    },
                }
                for tc in m.tool_calls
            ]
        if m.tool_call_id:
            d["tool_call_id"] = m.tool_call_id
        return d

    async def complete(self, request: CompletionRequest) -> Response:
        model = request.model or self._default_model
        messages = [self._serialize_message(m) for m in request.messages]
        if request.system:
            messages.insert(0, {"role": "system", "content": request.system})

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.response_schema:
            # Phase 11.y: gpt-4o family supports strict JSON Schema mode.
            # Older models (gpt-3.5, gpt-4 base) fall back to basic json_object.
            if _supports_strict_schema(model):
                kwargs["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "structured_output",
                        "schema": request.response_schema,
                        "strict": True,
                    },
                }
            else:
                kwargs["response_format"] = {"type": "json_object"}
        if request.tools:
            kwargs["tools"] = request.tools

        try:
            resp = await self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise classify_external_error(exc) from exc

        choice = resp.choices[0]
        usage = resp.usage
        input_tok = usage.prompt_tokens if usage else 0
        output_tok = usage.completion_tokens if usage else 0

        import json as _json
        metadata: dict[str, Any] = {}
        if choice.message.tool_calls:
            metadata["tool_calls"] = [
                {
                    "id": tc.id,
                    "function": {
                        "name": tc.function.name,
                        "arguments": _json.loads(tc.function.arguments or "{}"),
                    },
                }
                for tc in choice.message.tool_calls
            ]

        return Response(
            content=choice.message.content or "",
            model=model,
            usage=TokenUsage(input_tokens=input_tok, output_tokens=output_tok),
            finish_reason=choice.finish_reason or "stop",
            metadata=metadata,
        )

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]:
        model = request.model or self._default_model
        messages = [{"role": m.role, "content": m.content} for m in request.messages]

        try:
            response = await self._client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                stream=True,
            )
            async for chunk in response:  # type: ignore[union-attr]
                delta = chunk.choices[0].delta if chunk.choices else None
                content = (delta.content or "") if delta else ""
                is_final = bool(chunk.choices) and chunk.choices[0].finish_reason is not None
                usage = None
                if is_final and chunk.usage:
                    usage = TokenUsage(
                        input_tokens=chunk.usage.prompt_tokens,
                        output_tokens=chunk.usage.completion_tokens,
                    )
                yield StreamChunk(content=content, is_final=is_final, usage=usage)
        except Exception as exc:
            raise classify_external_error(exc) from exc

    async def embed(self, text: str, model: str | None = None) -> Embedding:
        embed_model = model or "text-embedding-3-small"
        try:
            resp = await self._client.embeddings.create(input=text, model=embed_model)
        except Exception as exc:
            raise classify_external_error(exc) from exc
        return Embedding(vector=resp.data[0].embedding, model=embed_model)

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
