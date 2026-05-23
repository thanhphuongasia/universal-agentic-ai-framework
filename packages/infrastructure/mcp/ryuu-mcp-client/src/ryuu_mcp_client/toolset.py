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
from dataclasses import dataclass, field
from typing import Any

from ryuu_mcp_core import IMCPClient, MCPToolSpec

from ryuu_mcp_client.mcp_tool import MCPTool

log = logging.getLogger("ryuu_mcp_client.toolset")


@dataclass
class MCPToolset:
    """Bundle of MCP tools sourced from multiple servers."""
    clients: list[IMCPClient]
    _tools: list[MCPTool] = field(default_factory=list, init=False)
    _started: bool = field(default=False, init=False)

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


__all__ = ["MCPToolset"]
