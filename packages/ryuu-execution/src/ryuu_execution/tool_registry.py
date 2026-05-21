"""ITool Protocol + ToolRegistry — framework-level tool-calling primitive."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ITool(Protocol):
    tool_id: str
    schema: dict[str, Any] | None

    async def execute(self, args: dict[str, Any]) -> Any: ...


_CallableHandler = Callable[..., Awaitable[Any]]


class _CallableWrapper:
    tool_id: str
    schema: dict[str, Any] | None = None

    def __init__(self, name: str, fn: _CallableHandler) -> None:
        self.tool_id = name
        self._fn = fn

    async def execute(self, args: dict[str, Any]) -> Any:
        return await self._fn(**args)


class ToolRegistry:
    """Maps tool name → ITool with optional per-tool domain allowlist."""

    def __init__(self) -> None:
        self._handlers: dict[str, ITool] = {}
        self._domains: dict[str, set[str] | None] = {}

    def register(
        self,
        name: str,
        tool: ITool | _CallableHandler,
        allowed_domains: set[str] | None = None,
    ) -> None:
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

    async def run(self, tool_call: dict[str, Any], domain: str = "") -> str:
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
        results = []
        for tc in tool_calls:
            content = await self.run(tc, domain=domain)
            results.append({"tool_call_id": tc["id"], "content": content})
        return results
