"""ryuu-mcp-client — MCP client + multi-server orchestration.

Connects Ryuu agents to any MCP server (filesystem, GitHub, Gmail, Brave
Search, custom, etc.) via Anthropic's MCP Python SDK underneath.

Public API:
    MCPClient            — single-server connection (IMCPClient impl)
    MCPTool              — adapts one MCP tool to ryuu-execution's ITool
    MCPToolset           — bundle of tools from multiple servers
    MCPSkillsLoader      — read skills.yaml → build clients

Quick start:
    from ryuu_mcp_client import MCPSkillsLoader, MCPToolset

    loader = MCPSkillsLoader.from_path("~/.ryuu/skills.yaml")
    toolset = MCPToolset(clients=loader.build_clients())
    await toolset.start_all()

    agent = Agent(tools=[*memory_tools, *toolset.tools], ...)
    # Chat — LLM can call any MCP tool naturally

    await toolset.stop_all()
"""

from ryuu_mcp_client.client import MCPClient
from ryuu_mcp_client.loader import MCPSkillsLoader
from ryuu_mcp_client.mcp_tool import MCPTool
from ryuu_mcp_client.toolset import MCPToolset

__version__ = "0.3.0a1"

__all__ = ["MCPClient", "MCPTool", "MCPToolset", "MCPSkillsLoader"]
