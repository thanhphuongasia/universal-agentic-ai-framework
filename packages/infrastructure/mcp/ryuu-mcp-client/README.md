# ryuu-mcp-client

MCP client + multi-server orchestration for Ryuu. Connect your agent to any MCP server (filesystem, GitHub, Gmail, Brave Search, Slack, custom) without writing Python code per server — just edit `skills.yaml`.

## Why use this

Adding capability to an agent traditionally requires:
1. Pick a Python library (e.g. `python-github`)
2. Write a tool wrapper function
3. Update agent's `tools=[...]`
4. Test, deploy

With MCP:
1. Find an MCP server (community ecosystem has dozens — GitHub, Gmail, FS, Slack, etc.)
2. Add 4 lines to `skills.yaml`
3. Restart agent — tools auto-discovered

## Skills config example

```yaml
# ~/.ryuu/skills.yaml
mcp_servers:
  filesystem:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/Users/macbook/Documents"]
  
  github:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: ${GITHUB_TOKEN}
  
  brave:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-brave-search"]
    env:
      BRAVE_API_KEY: ${BRAVE_API_KEY}
  
  legacy:
    command: ...
    enabled: false      # disable without removing the entry
```

## Usage

```python
from ryuu_mcp_client import MCPSkillsLoader, MCPToolset
from ryuu_knowledge_memory import MemoryToolset

loader = MCPSkillsLoader.from_path("~/.ryuu/skills.yaml")
mcp_toolset = MCPToolset(clients=loader.build_clients())
await mcp_toolset.start_all()

memory_toolset = MemoryToolset(backbone=my_backbone)

agent = Agent(
    model="gpt-4o-mini",
    tools=[*memory_toolset.tools, *mcp_toolset.tools],   # native + MCP
)
# LLM treats MCP tools indistinguishably from native ones via function calling

# On shutdown:
await mcp_toolset.stop_all()
```

## Tool naming convention

`<server_name>.<tool_name>` — qualified names prevent collisions when multiple servers expose tools with the same bare name (e.g. `filesystem.read_file` vs `github.read_file`). In the OpenAI function-calling schema, dots become underscores (`filesystem_read_file`) per OpenAI's name regex.

## Lifecycle

| Method | What happens |
|--------|-------------|
| `MCPClient.start()` | Spawns server subprocess, sends `initialize` JSON-RPC, awaits handshake |
| `MCPClient.list_tools()` | Sends `tools/list`, caches result |
| `MCPClient.call_tool(name, args)` | Sends `tools/call`, returns text content |
| `MCPClient.stop()` | Closes stdio, kills subprocess |

`MCPToolset` wraps N clients — `start_all` / `stop_all` for batch lifecycle.

## Error handling

- Server fails to start → logged warning, other servers proceed (graceful degrade)
- Server crashes during tool call → exception propagates to caller (Agent's error trap catches it for chat-friendly message)
