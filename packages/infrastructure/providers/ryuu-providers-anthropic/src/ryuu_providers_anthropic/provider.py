"""Anthropic ILLMProvider adapter.

Wraps ``anthropic.AsyncAnthropic`` and maps responses/errors to RYUU types.
Structured output uses the tool-use pattern (Anthropic lacks direct JSON mode).
Install with: ``pip install "ryuu-providers[anthropic]"``
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from ryuu_core.errors import classify_external_error
from ryuu_core.models import Cost

from ryuu_providers_core._pricing import calculate_usd
from ryuu_providers_core.llm import (
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

log = logging.getLogger(__name__)

_STRUCTURED_TOOL_NAME = "structured_output"

# Injected into system prompt when native thinking is unavailable (haiku, etc.)
_COT_SUFFIX = (
    "\n\nProduce your response in two parts:\n"
    "<thinking>\nReason step by step. Decompose the problem. "
    "Identify failure modes of a quick answer.\n</thinking>\n"
    "<answer>\nConcise, direct answer.\n</answer>\n"
    "Always emit BOTH tags."
)


def _is_thinking_unsupported(exc: Exception) -> bool:
    """True when the API rejected the thinking param (model doesn't support it)."""
    msg = str(exc).lower()
    return "thinking" in msg and (
        "not supported" in msg or "invalid" in msg or "unsupported" in msg
    )


def _is_temperature_rejected(exc: Exception) -> bool:
    """True when the API rejected the temperature param.

    Claude 5-family models (adaptive thinking always on) deprecate `temperature`
    and 400 on it; older models accept it. Retry without rather than maintaining
    a model list here.
    """
    msg = str(exc).lower()
    return "temperature" in msg and ("deprecated" in msg or "not supported" in msg)


def _to_anthropic_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """OpenAI function-calling schema → Anthropic tool schema.

    The whole RYUU stack (tool introspection, react loop, ToolRegistry) speaks the
    OpenAI wire format; translating HERE keeps the adapter the single place that
    knows Anthropic's shape. Already-Anthropic-shaped dicts pass through untouched.
    """
    out: list[dict[str, Any]] = []
    for t in tools or []:
        fn = t.get("function") if t.get("type") == "function" else None
        if fn:
            out.append({
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters")
                or {"type": "object", "properties": {}},
            })
        else:
            out.append(t)
    return out


def _to_anthropic_messages(
    messages: list[Any], system: str | None
) -> tuple[list[dict[str, Any]], str]:
    """RYUU Message list (OpenAI roles) → Anthropic messages + top-level system.

    - role "system"                → hoisted into the returned system string
      (Anthropic 400s on system-role messages: "use the top-level 'system' parameter")
    - assistant with tool_calls    → content blocks [text?, tool_use...]
    - role "tool"                  → user message with tool_result block; consecutive
      tool results merge into ONE user message (Anthropic wants all results for an
      assistant turn in the single following user message)
    """
    system_parts: list[str] = [system] if system else []
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "system":
            system_parts.append(m.content)
        elif m.role == "assistant" and getattr(m, "tool_calls", None):
            blocks: list[dict[str, Any]] = []
            if m.content:
                blocks.append({"type": "text", "text": m.content})
            for tc in m.tool_calls:
                fn = tc.get("function") or {}
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args or "{}")
                    except ValueError:
                        args = {"_raw": args}
                blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id", ""),
                    "name": fn.get("name", ""),
                    "input": args or {},
                })
            out.append({"role": "assistant", "content": blocks})
        elif m.role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": getattr(m, "tool_call_id", None) or "",
                "content": m.content,
            }
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
        else:
            out.append({"role": m.role, "content": m.content})
    return out, "\n\n".join(p for p in system_parts if p)


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
            raise ImportError('Install anthropic: pip install "ryuu-providers[anthropic]"')

        self._client = AsyncAnthropic(api_key=api_key, **client_kwargs)
        self._default_model = default_model

    async def complete(self, request: CompletionRequest) -> Response:
        model = request.model or self._default_model
        messages, system = _to_anthropic_messages(request.messages, request.system)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if system:
            kwargs["system"] = system

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
            kwargs["tools"] = _to_anthropic_tools(request.tools)

        used_native_thinking = False
        cot_injected = False

        if request.thinking_budget:
            # max_tokens must exceed budget_tokens; Anthropic enforces this.
            kwargs["max_tokens"] = max(kwargs["max_tokens"], request.thinking_budget + 100)
            # Thinking mode requires temperature=1 (Anthropic requirement).
            kwargs.pop("temperature", None)
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": request.thinking_budget}
            log.debug(
                "anthropic.complete thinking=native model=%s budget_tokens=%d max_tokens=%d",
                model, request.thinking_budget, kwargs["max_tokens"],
            )

        try:
            resp = await self._client.messages.create(**kwargs)
            if request.thinking_budget:
                used_native_thinking = True
        except Exception as exc:
            if "temperature" in kwargs and _is_temperature_rejected(exc):
                kwargs.pop("temperature", None)
                log.debug("anthropic.complete temperature rejected by model=%s → retry without", model)
                try:
                    resp = await self._client.messages.create(**kwargs)
                except Exception as exc2:
                    raise classify_external_error(exc2) from exc2
            elif request.thinking_budget and _is_thinking_unsupported(exc):
                # Model doesn't support native thinking → fall back to CoT prompt.
                log.warning(
                    "anthropic.complete thinking=native UNSUPPORTED model=%s "
                    "budget_tokens=%d → falling back to CoT prompt",
                    model, request.thinking_budget,
                )
                kwargs.pop("thinking", None)
                kwargs["system"] = (kwargs.get("system") or "") + _COT_SUFFIX
                try:
                    resp = await self._client.messages.create(**kwargs)
                    cot_injected = True
                except Exception as exc2:
                    raise classify_external_error(exc2) from exc2
            else:
                raise classify_external_error(exc) from exc

        content_text = ""
        tool_calls: list[dict[str, Any]] = []
        thinking: list[str] = []

        for block in resp.content:
            if block.type == "text":
                content_text = block.text
            elif block.type == "thinking":
                thinking.append(getattr(block, "thinking", ""))
            elif block.type == "tool_use":
                if block.name == _STRUCTURED_TOOL_NAME:
                    content_text = json.dumps(block.input)
                else:
                    tool_calls.append({
                        "id": block.id,
                        "function": {
                            "name": block.name,
                            "arguments": block.input,
                        },
                    })

        usage = resp.usage
        thinking_tokens = getattr(usage, "cache_creation_input_tokens", 0)  # proxy when absent

        log.debug(
            "anthropic.complete done model=%s input=%d output=%d "
            "thinking_blocks=%d native=%s cot_fallback=%s",
            model,
            usage.input_tokens,
            usage.output_tokens,
            len(thinking),
            used_native_thinking,
            cot_injected,
        )

        return Response(
            content=content_text,
            model=model,
            usage=TokenUsage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
            ),
            finish_reason=resp.stop_reason or "end_turn",
            tool_calls=tool_calls,
            thinking=thinking,
            metadata={
                "thinking_native": used_native_thinking,
                "thinking_cot_fallback": cot_injected,
            },
        )

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]:
        model = request.model or self._default_model
        messages, system = _to_anthropic_messages(request.messages, request.system)

        try:
            async with self._client.messages.stream(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                max_tokens=request.max_tokens,
                system=system,
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
