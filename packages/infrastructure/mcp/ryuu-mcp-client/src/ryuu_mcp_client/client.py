"""MCPClient — one running MCP server connection.

Wraps Anthropic's `mcp` Python SDK (`ClientSession + stdio_client`). Manages
lifecycle (start subprocess + initialize handshake → tool discovery → call →
stop). Multi-server orchestration lives in `MCPSkillsLoader`.

Why wrap Anthropic SDK instead of using it directly:
  • Our framework presents a smaller, stable surface (IMCPClient Protocol)
  • Hide SDK version upgrades from consumers
  • Add framework-specific concerns (logging, error mapping, lifecycle hooks)
"""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

from ryuu_mcp_core import IMCPClient, MCPServerConfig, MCPToolSpec

log = logging.getLogger("ryuu_mcp_client")


@dataclass
class MCPClient(IMCPClient):
    """Single-server MCP client. Lifecycle:

        client = MCPClient(config=MCPServerConfig(name="fs", command="npx", args=["..."]))
        await client.start()
        tools = await client.list_tools()
        result = await client.call_tool("read_file", {"path": "/foo"})
        await client.stop()

    Or use as an async context manager (Phase 9.x — not yet implemented).
    """
    config: MCPServerConfig
    _session: Any = field(default=None, init=False)
    _exit_stack: AsyncExitStack | None = field(default=None, init=False)
    _tools_cache: list[MCPToolSpec] | None = field(default=None, init=False)

    async def start(self) -> None:
        """Spawn MCP server subprocess + JSON-RPC initialize handshake."""
        if self._session is not None:
            return  # already started

        # Import lazily so this module can be loaded without the SDK
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=self.config.command,
            args=list(self.config.args),
            env=dict(self.config.env) if self.config.env else None,
        )

        self._exit_stack = AsyncExitStack()
        try:
            read, write = await self._exit_stack.enter_async_context(stdio_client(params))
            session = await self._exit_stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self._session = session
            log.info("MCP server %r started", self.config.name)
        except Exception:
            # Ensure subprocess gets killed if init fails
            if self._exit_stack is not None:
                await self._exit_stack.aclose()
                self._exit_stack = None
            raise

    async def stop(self) -> None:
        """Send shutdown + close subprocess stdio."""
        if self._exit_stack is not None:
            try:
                await self._exit_stack.aclose()
            except Exception as exc:  # noqa: BLE001 — best-effort shutdown
                log.warning("MCP server %r stop failed: %s", self.config.name, exc)
            finally:
                self._exit_stack = None
                self._session = None
                self._tools_cache = None
        log.info("MCP server %r stopped", self.config.name)

    async def list_tools(self) -> list[MCPToolSpec]:
        """Fetch tool definitions from the server. Cached after first call.

        Returns specs with qualified_name like `filesystem.read_file`.
        """
        if self._session is None:
            raise RuntimeError("MCPClient not started — call .start() first")

        if self._tools_cache is not None:
            return self._tools_cache

        response = await self._session.list_tools()
        specs = [
            MCPToolSpec(
                server_name=self.config.name,
                name=tool.name,
                description=tool.description or "",
                input_schema=dict(tool.inputSchema) if tool.inputSchema else {},
            )
            for tool in response.tools
        ]
        self._tools_cache = specs
        log.info("MCP server %r exposes %d tools", self.config.name, len(specs))
        return specs

    async def call_tool(self, name: str, args: dict[str, Any]) -> str:
        """Invoke a tool. Returns first text content from response.

        For multi-modal tools (image / audio), text content is preferred;
        binary parts are summarized as `<bytes len=N>`.
        """
        if self._session is None:
            raise RuntimeError("MCPClient not started — call .start() first")

        result = await self._session.call_tool(name, args)
        # MCP returns a list of content parts (text / image / resource)
        parts: list[str] = []
        for c in (result.content or []):
            if hasattr(c, "text") and c.text:
                parts.append(c.text)
            elif hasattr(c, "type"):
                parts.append(f"<{c.type} content>")
            else:
                parts.append(str(c))
        return "\n".join(parts) if parts else ""
