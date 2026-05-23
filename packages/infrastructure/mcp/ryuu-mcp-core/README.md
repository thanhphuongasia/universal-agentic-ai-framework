# ryuu-mcp-core

Protocols + value types for the MCP (Model Context Protocol) integration layer. Zero external dependencies.

## Public API

| Type | Purpose |
|------|---------|
| `MCPServerConfig` | Frozen dataclass — one entry from `skills.yaml` (server name, command, args, env). |
| `MCPToolSpec` | Frozen dataclass — describes a tool exposed by a server (server name, tool name, description, JSON Schema). |
| `IMCPClient` | Protocol — what `ryuu-mcp-client.MCPClient` implements. Lifecycle: `start → list_tools → call_tool* → stop`. |

## Why this package

Separates the **contracts** from the **implementation**. Future product can swap the concrete client (Anthropic SDK, Rust-based, custom JSON-RPC) without touching consumer code that depends on `IMCPClient`.

Consumers (e.g. `RyuuHandler`, `MCPSkillsLoader`) depend on this package only. The concrete client wrapping Anthropic's `mcp` Python SDK ships in `ryuu-mcp-client`.
