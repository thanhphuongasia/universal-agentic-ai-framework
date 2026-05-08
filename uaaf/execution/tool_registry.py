"""ITool Protocol + ToolRegistry — framework-level tool-calling primitive.

Tool schemas live in YAML (prompts/*/v*.yaml); this module handles registration
and dispatch only. Domain whitelisting enforces that agents cannot accidentally
invoke tools from a different product's namespace.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ITool(Protocol):
    """Contract for tools the LLM can call.

    ``schema`` is the OpenAI function schema dict (or None if schema lives
    in the YAML prompt registry and is injected at request-build time).
    """

    tool_id: str
    schema: dict[str, Any] | None

    async def execute(self, args: dict[str, Any]) -> Any: ...


# Callable handler form — async function or coroutine function accepting kwargs.
_CallableHandler = Callable[..., Awaitable[Any]]


class _CallableWrapper:
    """Wraps a bare async callable so it satisfies ITool for internal use."""

    tool_id: str
    schema: dict[str, Any] | None = None

    def __init__(self, name: str, fn: _CallableHandler) -> None:
        self.tool_id = name
        self._fn = fn

    async def execute(self, args: dict[str, Any]) -> Any:
        return await self._fn(**args)


class ToolRegistry:
    """Maps tool name → ITool with optional per-tool domain allowlist.

    ``allowed_domains=None`` on a registration means all domains may invoke
    that tool. Pass a non-empty set to restrict access.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, ITool] = {}
        self._domains: dict[str, set[str] | None] = {}

    def register(
        self,
        name: str,
        tool: ITool | _CallableHandler,
        allowed_domains: set[str] | None = None,
    ) -> None:
        """Register a tool under *name*.

        *tool* may be an ``ITool`` instance or a plain async callable.
        *allowed_domains=None* permits any domain (no restriction).
        """
        if isinstance(tool, ITool):
            self._handlers[name] = tool
        else:
            self._handlers[name] = _CallableWrapper(name, tool)
        self._domains[name] = allowed_domains

    def _check_domain(self, name: str, domain: str) -> None:
        allowed = self._domains.get(name)
        if allowed is not None and domain not in allowed:
            raise PermissionError(
                f"Tool '{name}' not allowed for domain '{domain}'. "
                f"Allowed: {allowed}"
            )

    async def run(
        self,
        tool_call: dict[str, Any],
        domain: str = "",
    ) -> str:
        """Execute one tool_call dict, return JSON string result."""
        name = tool_call["function"]["name"]
        args = tool_call["function"]["arguments"]
        handler = self._handlers.get(name)
        if handler is None:
            return json.dumps({"error": f"Unknown tool: {name}"})
        self._check_domain(name, domain)
        try:
            result = await handler.execute(args)
        except Exception as exc:
            return json.dumps({"error": str(exc)})
        return json.dumps(result, default=str)

    async def run_all(
        self,
        tool_calls: list[dict[str, Any]],
        domain: str = "",
    ) -> list[dict[str, Any]]:
        """Run all tool_calls and return [{tool_call_id, content}] list."""
        results = []
        for tc in tool_calls:
            content = await self.run(tc, domain=domain)
            results.append({"tool_call_id": tc["id"], "content": content})
        return results
