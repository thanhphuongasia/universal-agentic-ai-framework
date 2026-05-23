"""MCP layer Protocols + value types.

Lightweight contracts that don't depend on Anthropic's mcp SDK. Concrete
client lives in `ryuu-mcp-client` and wraps the SDK underneath.

This separation lets future products that want to swap MCP SDK (e.g. for
a Rust-based client, or hand-rolled JSON-RPC) keep the same surface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Server config — what users write in skills.yaml
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MCPServerConfig:
    """One MCP server entry from skills.yaml.

    Example:
        MCPServerConfig(
            name="filesystem",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
            env={"NODE_ENV": "production"},
        )
    """
    name: str
    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True


# ---------------------------------------------------------------------------
# Tool spec — what an MCP server reports
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MCPToolSpec:
    """A tool exposed by an MCP server. Reported via tools/list."""
    server_name: str            # which server published this
    name: str                    # tool name as the server defines it
    description: str
    input_schema: dict[str, Any]   # JSON Schema for arguments

    @property
    def qualified_name(self) -> str:
        """`<server>.<tool>` — used to avoid name collisions across servers.

        E.g. filesystem.read_file vs github.read_file would conflict if we
        used bare names. Always qualify.
        """
        return f"{self.server_name}.{self.name}"


# ---------------------------------------------------------------------------
# Client Protocol — what concrete impls (ryuu-mcp-client) implement
# ---------------------------------------------------------------------------

@runtime_checkable
class IMCPClient(Protocol):
    """One client = one running MCP server connection. Lifecycle: start →
    list_tools → call_tool (* N) → stop.

    Concrete impl (in ryuu-mcp-client) wraps Anthropic's mcp.ClientSession.
    """
    config: MCPServerConfig

    async def start(self) -> None:
        """Spawn server subprocess + JSON-RPC handshake (initialize)."""
        ...

    async def stop(self) -> None:
        """Send shutdown, close stdio."""
        ...

    async def list_tools(self) -> list[MCPToolSpec]:
        """Discover tools the server exposes."""
        ...

    async def call_tool(self, name: str, args: dict[str, Any]) -> str:
        """Invoke a tool by name. Returns text content from server's response."""
        ...


__all__ = [
    "MCPServerConfig",
    "MCPToolSpec",
    "IMCPClient",
]
