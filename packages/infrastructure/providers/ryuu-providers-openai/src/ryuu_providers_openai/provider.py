"""OpenAI ILLMProvider adapter.

Wraps ``openai.AsyncOpenAI`` and maps its responses/errors to RYUU types.
Install with: ``pip install "ryuu-providers[openai]"``
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from ryuu_core.errors import classify_external_error
from ryuu_core.models import Cost

from ryuu_providers_core._pricing import calculate_usd
from ryuu_providers_core.llm import (
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

log = logging.getLogger(__name__)

# Phase 11.y — OpenAI models supporting strict JSON Schema mode.
# gpt-4o, gpt-4o-mini, o1, o3 series. Older models (gpt-3.5, gpt-4 base)
# fall back to basic `response_format={"type": "json_object"}`.
_STRICT_SCHEMA_PREFIXES = ("gpt-4o", "gpt-5", "o1", "o3", "o4")

# CoT prompt injected when thinking_budget set but model has no native reasoning.
_COT_SUFFIX = (
    "\n\nProduce your response in two parts:\n"
    "<thinking>\nReason step by step. Decompose the problem. "
    "Identify failure modes of a quick answer.\n</thinking>\n"
    "<answer>\nConcise, direct answer.\n</answer>\n"
    "Always emit BOTH tags."
)


def _supports_strict_schema(model: str) -> bool:
    """Detect if model supports `response_format={"type": "json_schema", ...}`."""
    return any(model.startswith(prefix) for prefix in _STRICT_SCHEMA_PREFIXES)


def _is_unsupported_param_error(exc: Exception) -> bool:
    """True when API rejected a parameter the model doesn't support (e.g. temperature on o-series)."""
    msg = str(exc).lower()
    return "unsupported_parameter" in msg or (
        "temperature" in msg and ("not supported" in msg or "unsupported" in msg)
    )


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

        cot_injected = False

        # thinking_budget on OpenAI: o-series thinks implicitly (no opt-in flag).
        # For non-o-series models, inject CoT prompt as fallback.
        if request.thinking_budget:
            log.debug(
                "openai.complete thinking_budget=%d model=%s → will try; "
                "o-series thinks implicitly, others get CoT injection",
                request.thinking_budget, model,
            )

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
            if _is_unsupported_param_error(exc):
                # o-series rejects temperature + uses max_completion_tokens.
                # Detected at runtime — no hardcoded model list needed.
                log.debug(
                    "openai.complete model=%s rejected temperature → retrying "
                    "without temperature, switching to max_completion_tokens",
                    model,
                )
                kwargs.pop("temperature", None)
                kwargs["max_completion_tokens"] = kwargs.pop("max_tokens", 1024)
                if request.thinking_budget and request.messages:
                    # o-series thinks implicitly — inject CoT only for non-o models.
                    # Since we got an unsupported-param error, this IS an o-series.
                    pass  # no CoT needed, reasoning is implicit
                try:
                    resp = await self._client.chat.completions.create(**kwargs)
                except Exception as exc2:
                    raise classify_external_error(exc2) from exc2
            else:
                # Non-o-series + thinking_budget → inject CoT into system prompt.
                if request.thinking_budget:
                    log.debug(
                        "openai.complete model=%s has no native thinking → CoT injection",
                        model,
                    )
                    sys_msg = next(
                        (m for m in messages if m.get("role") == "system"), None
                    )
                    if sys_msg:
                        sys_msg["content"] = (sys_msg["content"] or "") + _COT_SUFFIX
                    else:
                        messages.insert(0, {"role": "system", "content": _COT_SUFFIX.strip()})
                    cot_injected = True
                    try:
                        resp = await self._client.chat.completions.create(**kwargs)
                    except Exception as exc2:
                        raise classify_external_error(exc2) from exc2
                else:
                    raise classify_external_error(exc) from exc

        choice = resp.choices[0]
        usage = resp.usage
        input_tok = usage.prompt_tokens if usage else 0
        output_tok = usage.completion_tokens if usage else 0

        # Extract reasoning_tokens from o-series usage (hidden content, visible count).
        reasoning_tokens = 0
        if usage and hasattr(usage, "completion_tokens_details") and usage.completion_tokens_details:
            reasoning_tokens = getattr(usage.completion_tokens_details, "reasoning_tokens", 0) or 0

        log.debug(
            "openai.complete done model=%s input=%d output=%d reasoning_tokens=%d cot_fallback=%s",
            model, input_tok, output_tok, reasoning_tokens, cot_injected,
        )

        import json as _json
        tool_calls: list[dict[str, Any]] = []
        if choice.message.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "function": {
                        "name": tc.function.name,
                        "arguments": _json.loads(tc.function.arguments or "{}"),
                    },
                }
                for tc in choice.message.tool_calls
            ]

        metadata: dict[str, Any] = {"thinking_cot_fallback": cot_injected}
        if reasoning_tokens:
            metadata["reasoning_tokens"] = reasoning_tokens

        return Response(
            content=choice.message.content or "",
            model=model,
            usage=TokenUsage(input_tokens=input_tok, output_tokens=output_tok),
            finish_reason=choice.finish_reason or "stop",
            tool_calls=tool_calls,
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
