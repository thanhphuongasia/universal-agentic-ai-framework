"""OAuth 2.0 PKCE helpers — generic, server-agnostic.

For OAuth-based remote MCP servers (HTTP/SSE transport) where the run wrapper
needs a Bearer token that auto-refreshes. Two console scripts are exposed:

  • ryuu-mcp-oauth-pkce  — one-shot login (RFC 7636 PKCE + optional RFC 7591
    dynamic client registration). Writes tokens to disk.
  • ryuu-mcp-oauth-run   — auto-refreshes token, then exec's `npx mcp-remote`
    to bridge the remote HTTP MCP to the bot's stdio.

Both take `--config <path>` pointing to a JSON describing the server's OAuth
endpoints. See the package README for the config schema.
"""

from ryuu_mcp_client.oauth.pkce import main as pkce_main
from ryuu_mcp_client.oauth.runner import main as runner_main

__all__ = ["pkce_main", "runner_main"]
