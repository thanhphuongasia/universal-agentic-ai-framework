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

    Naming model:
      • spec.name           = bare tool name as the MCP server reports it
                              (e.g. "list_directory"). This is what we pass
                              when calling `client.call_tool()`.
      • spec.qualified_name = "<server>.<bare>" (e.g. "filesystem.list_directory")
                              — display only.
      • tool_id             = "<server>_<bare>" (e.g. "filesystem_list_directory")
                              — registry key + OpenAI schema function name.

    OpenAI's function-calling regex forbids dots in tool names, so we
    underscore-qualify them. The factory registers by `tool_id`, the LLM
    emits tool_use with the schema's `function.name`, and the two must
    match exactly. Hence both derive from the same underscored form.
    """
    client: IMCPClient
    spec: MCPToolSpec

    @property
    def tool_id(self) -> str:
        # Must equal schema.function.name so tool_registry lookup succeeds
        # when the LLM emits a tool_use call.
        return self.spec.qualified_name.replace(".", "_")

    @property
    def schema(self) -> dict[str, Any] | None:
        """OpenAI function-calling schema. Uses server's reported input_schema."""
        return {
            "type": "function",
            "function": {
                "name": self.tool_id,
                "description": self.spec.description,
                "parameters": self.spec.input_schema or {"type": "object", "properties": {}},
            },
        }

    async def execute(self, args: dict[str, Any]) -> Any:
        """Invoke via the underlying MCPClient, return text content."""
        # NB: pass the BARE name (spec.name) to the MCP server — it doesn't
        # know about our qualified / underscored variants.
        return await self.client.call_tool(self.spec.name, args)


__all__ = ["MCPTool"]
