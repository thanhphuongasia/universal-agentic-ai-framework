"""MCPToolset — multi-server tool bundle for `Agent(tools=[...])`.

Pattern parallel to `MemoryToolset`. Wraps one or more `MCPClient`s, exposes
`.tools` as a list of `ITool` impls (MCPTool wrappers) that Agent factory
consumes alongside native Python tools.

Lifecycle:
    toolset = MCPToolset(clients=[fs_client, gh_client])
    await toolset.start_all()      # launches subprocesses + lists tools
    agent = Agent(tools=toolset.tools, ...)
    ...
    await toolset.stop_all()       # graceful shutdown all servers
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from ryuu_mcp_core import IMCPClient, MCPToolSpec

from ryuu_mcp_client.client import MCPClient
from ryuu_mcp_client.mcp_tool import MCPTool

log = logging.getLogger("ryuu_mcp_client.toolset")

# Callback invoked after tools added/removed at runtime. Used by the host
# (e.g. RyuuHandler) to invalidate any cached Agent instances so the next
# turn rebuilds with the new tool set.
ToolsetChangeListener = Callable[["MCPToolset"], Awaitable[None] | None]


@dataclass
class MCPToolset:
    """Bundle of MCP tools sourced from multiple servers.

    Lifecycle:
        toolset = MCPToolset(clients=[...])
        await toolset.start_all()            # boot all configured at construction
        await toolset.add_server(cfg)        # hot-add (Phase 8.11)
        await toolset.remove_server("name")  # hot-remove
        await toolset.stop_all()
    """
    clients: list[IMCPClient]
    _tools: list[MCPTool] = field(default_factory=list, init=False)
    _started: bool = field(default=False, init=False)
    _listeners: list[ToolsetChangeListener] = field(default_factory=list, init=False)

    async def start_all(self) -> None:
        """Launch all servers + collect their tools into a unified list.

        Continues if individual servers fail to start — partial degradation
        is better than total failure when one MCP package is broken.
        """
        if self._started:
            return
        for client in self.clients:
            try:
                await client.start()
            except Exception as exc:  # noqa: BLE001
                log.warning("MCP server %r failed to start: %s", client.config.name, exc)
                continue
            try:
                specs = await client.list_tools()
                for spec in specs:
                    self._tools.append(MCPTool(client=client, spec=spec))
            except Exception as exc:  # noqa: BLE001
                log.warning("MCP server %r list_tools failed: %s", client.config.name, exc)
        self._started = True
        log.info("MCPToolset ready: %d tools from %d servers", len(self._tools), len(self.clients))

    async def stop_all(self) -> None:
        for client in self.clients:
            try:
                await client.stop()
            except Exception as exc:  # noqa: BLE001 — best effort
                log.warning("MCP server %r stop failed: %s", client.config.name, exc)
        self._tools.clear()
        self._started = False

    @property
    def tools(self) -> list[MCPTool]:
        """ITool-compatible list ready for `Agent(tools=...)`."""
        return list(self._tools)

    def list_specs(self) -> list[MCPToolSpec]:
        """Just the specs (for debug / inspection)."""
        return [t.spec for t in self._tools]

    def server_summary(self) -> dict[str, int]:
        """{server_name: tool_count} — used for /status display."""
        summary: dict[str, int] = {}
        for t in self._tools:
            summary[t.spec.server_name] = summary.get(t.spec.server_name, 0) + 1
        return summary

    # ----- Phase 8.11 — hot install/uninstall --------------------------- #

    def has_server(self, name: str) -> bool:
        return any(c.config.name == name for c in self.clients)

    def add_listener(self, fn: ToolsetChangeListener) -> None:
        """Register a callback fired AFTER tools are added/removed.

        Host uses this to invalidate cached Agent instances. Callback may be
        sync or async — both are awaited if async.
        """
        self._listeners.append(fn)

    async def _notify_listeners(self) -> None:
        for fn in self._listeners:
            try:
                result = fn(self)
                if hasattr(result, "__await__"):
                    await result  # type: ignore[misc]
            except Exception as exc:  # noqa: BLE001
                log.warning("Toolset change listener raised: %s", exc)

    async def add_server(self, config: Any) -> list[MCPToolSpec]:
        """Hot-install a new MCP server. Returns the discovered tool specs.

        If a server with the same name already exists, raises ValueError.
        On startup failure, the (un-started) client is removed and exception
        is re-raised — toolset state stays consistent.
        """
        from ryuu_mcp_core import MCPServerConfig  # local import to avoid cycle

        if not isinstance(config, MCPServerConfig):
            raise TypeError(f"add_server() expects MCPServerConfig, got {type(config).__name__}")
        if self.has_server(config.name):
            raise ValueError(f"Server {config.name!r} already installed — uninstall first")

        client = MCPClient(config=config)
        self.clients.append(client)
        try:
            await client.start()
            specs = await client.list_tools()
        except Exception:
            # Roll back: remove from list, attempt cleanup
            self.clients.remove(client)
            try:
                await client.stop()
            except Exception:  # noqa: BLE001 — best effort
                pass
            raise

        for spec in specs:
            self._tools.append(MCPTool(client=client, spec=spec))
        log.info("MCPToolset hot-added %r (%d tools)", config.name, len(specs))
        await self._notify_listeners()
        return specs

    async def remove_server(self, name: str) -> int:
        """Hot-uninstall a server by name. Returns tool count removed.

        Stops the client subprocess and drops its tools from the bundle.
        Raises KeyError if no such server.
        """
        client = next((c for c in self.clients if c.config.name == name), None)
        if client is None:
            raise KeyError(f"No server named {name!r}")

        before = len(self._tools)
        self._tools = [t for t in self._tools if t.client is not client]
        removed = before - len(self._tools)
        self.clients.remove(client)
        try:
            await client.stop()
        except Exception as exc:  # noqa: BLE001
            log.warning("Stop of %r failed during remove: %s", name, exc)
        log.info("MCPToolset hot-removed %r (%d tools)", name, removed)
        await self._notify_listeners()
        return removed


__all__ = ["MCPToolset", "ToolsetChangeListener"]
