"""MCPTool — bridges MCP server tools to ryuu-execution's ITool protocol.

Each MCP tool reported by `client.list_tools()` becomes an MCPTool instance.
The Agent factory accepts ITool implementations directly via `tools=[...]`
(see `ryuu_execution.tool_registry.ToolRegistry.register`).

JSON Schema (`input_schema`) flows from server → ITool.schema → OpenAI
function-calling format unchanged. LLM sees MCP tools indistinguishably
from native Python tools.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ryuu_mcp_core import IMCPClient, MCPToolSpec


@dataclass
class MCPTool:
    """Adapts one MCP tool to ryuu-execution's `ITool` Protocol.

    `tool_id` uses the QUALIFIED name (`<server>.<tool>`) to prevent
    collisions when multiple MCP servers expose tools with the same bare name.
    """
    client: IMCPClient
    spec: MCPToolSpec

    @property
    def tool_id(self) -> str:
        return self.spec.qualified_name

    @property
    def schema(self) -> dict[str, Any] | None:
        """OpenAI function-calling schema. Uses server's reported input_schema."""
        return {
            "type": "function",
            "function": {
                "name": self.spec.qualified_name.replace(".", "_"),   # OpenAI dislikes "." in names
                "description": self.spec.description,
                "parameters": self.spec.input_schema or {"type": "object", "properties": {}},
            },
        }

    async def execute(self, args: dict[str, Any]) -> Any:
        """Invoke via the underlying MCPClient, return text content."""
        return await self.client.call_tool(self.spec.name, args)


__all__ = ["MCPTool"]
