"""ryuu-mcp-core — MCP Protocols + value types.

Public API:
    MCPServerConfig    — config for one MCP server (skills.yaml entry)
    MCPToolSpec        — a tool exposed by a server
    IMCPClient         — Protocol implemented by ryuu-mcp-client.MCPClient
"""

from ryuu_mcp_core.protocols import (
    IMCPClient,
    MCPServerConfig,
    MCPToolSpec,
)

__version__ = "0.3.0a1"

__all__ = ["IMCPClient", "MCPServerConfig", "MCPToolSpec"]
