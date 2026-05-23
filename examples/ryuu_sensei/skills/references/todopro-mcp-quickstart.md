# Task-Master-Pro MCP Server — Quickstart

MCP endpoint: `https://todopro.jacons-corp.com/mcp`  
Health check: `https://todopro.jacons-corp.com/health`  
Protocol: MCP StreamableHTTP (JSON-RPC 2.0 over SSE)

---

## Authentication

Every request requires a Bearer token in the `Authorization` header.

**Option A — Use an existing JWT** (from a previous login):
```
Authorization: Bearer <jwt-token>
```

**Option B — Login via MCP tool** (no token yet):
Call the `login` tool first. The server stores the session for the current connection.

**Option C — OAuth 2.0 PKCE** (for agents acting on behalf of a user):
See [OAuth login flow](#oauth-login-flow-for-agents) below.

---

## Connecting (OpenClaw / Hermes / any MCP client)

Add to your agent's MCP config:

```json
{
  "mcpServers": {
    "task-master-pro": {
      "url": "https://todopro.jacons-corp.com/mcp",
      "headers": {
        "Authorization": "Bearer <user-jwt-token>"
      }
    }
  }
}
```

For stdio-based clients (Claude Desktop, Claude Code):

```json
{
  "mcpServers": {
    "task-master-pro": {
      "type": "stdio",
      "command": "node",
      "args": ["packages/mcp-server/dist/index.js"],
      "env": {
        "TASKMASTER_API_URL": "https://todopro.jacons-corp.com/api",
        "TASKMASTER_TOKEN": "<user-jwt-token>"
      }
    }
  }
}
```

---

## Available Tools (26 total)

| Group | Tools |
|-------|-------|
| Auth | `login`, `logout` |
| Tasks | `list_tasks`, `get_task`, `get_today_tasks`, `create_task`, `update_task`, `complete_task`, `reopen_task`, `add_task_comment`, `log_effort` |
| Goals | `list_goals`, `get_goal`, `create_goal`, `update_goal` |
| Habits | `list_habits`, `create_habit`, `checkin_habit` |
| Projects | `list_projects`, `create_project` |
| Journal | `list_journal_entries`, `create_journal_entry` |
| Stats | `get_stats_overview`, `get_streaks` |
| Meta | `list_life_areas`, `list_tags` |

---

## Quick Test (curl)

```bash
TOKEN="<your-jwt-token>"

# Health check
curl https://todopro.jacons-corp.com/health

# MCP initialize handshake
curl -X POST https://todopro.jacons-corp.com/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}'
```

Expected response:
```
event: message
data: {"result":{"protocolVersion":"2024-11-05","capabilities":{"tools":{"listChanged":true}},"serverInfo":{"name":"task-master-pro","version":"1.0.0"}},"jsonrpc":"2.0","id":1}
```

---

## OAuth Login Flow (for agents)

Use this when the agent needs to act on behalf of a real user without storing their password.

### Step 1 — Register your agent as an OAuth client (one-time)

```bash
curl -X POST https://todopro.jacons-corp.com/api/oauth/register \
  -H "Content-Type: application/json" \
  -d '{
    "redirect_uris": ["https://your-agent-callback.example.com/oauth/callback"]
  }'
```

Response:
```json
{
  "client_id": "abc123...",
  "redirect_uris": ["https://your-agent-callback.example.com/oauth/callback"],
  "grant_types": ["authorization_code", "refresh_token"]
}
```

Save `client_id` — used for all future auth requests.

### Step 2 — Generate PKCE values

```js
const crypto = require('crypto')

const codeVerifier = crypto.randomBytes(32).toString('base64url')
const codeChallenge = crypto
  .createHash('sha256')
  .update(codeVerifier)
  .digest('base64url')
const state = crypto.randomBytes(16).toString('hex')
```

### Step 3 — Build the login URL and send to user

```js
const params = new URLSearchParams({
  client_id: '<your-client-id>',
  redirect_uri: 'https://your-agent-callback.example.com/oauth/callback',
  response_type: 'code',
  code_challenge: codeChallenge,
  code_challenge_method: 'S256',
  state: state,
})

const loginUrl = `https://todopro.jacons-corp.com/api/oauth/authorize?${params}`
// Send loginUrl to user via Telegram/Slack/email
```

The user sees a login form, enters email + password, and is redirected to your `redirect_uri?code=xxx&state=yyy`.

### Step 4 — Exchange code for tokens

```bash
curl -X POST https://todopro.jacons-corp.com/api/oauth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=authorization_code" \
  -d "code=<code-from-redirect>" \
  -d "redirect_uri=https://your-agent-callback.example.com/oauth/callback" \
  -d "client_id=<your-client-id>" \
  -d "code_verifier=<code-verifier-from-step-2>"
```

Response:
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 3600,
  "refresh_token": "a3f9..."
}
```

- `access_token`: valid 1 hour — use as Bearer token for all MCP calls
- `refresh_token`: valid 90 days, rotated on each use

### Step 5 — Refresh when access token expires

```bash
curl -X POST https://todopro.jacons-corp.com/api/oauth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=refresh_token" \
  -d "refresh_token=<your-refresh-token>" \
  -d "client_id=<your-client-id>"
```

Returns a new `access_token` + `refresh_token`. Store the new refresh token; the old one is revoked.

---

## Well-Known Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /.well-known/oauth-protected-resource` | MCP OAuth discovery (RFC 9728) |
| `GET /.well-known/oauth-authorization-server` | Redirects to backend auth server metadata |
| `GET /api/oauth/authorize` | Login form (browser) |
| `POST /api/oauth/authorize` | Process login, issue auth code |
| `POST /api/oauth/token` | Exchange code or refresh token |
| `POST /api/oauth/register` | Register new OAuth client (RFC 7591) |

---

## Token via MCP `login` tool (simple, no browser)

For trusted agents that hold user credentials:

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "login",
    "arguments": {
      "email": "user@example.com",
      "password": "secret"
    }
  }
}
```

The session token is stored server-side for the duration of the MCP session. No refresh — re-call `login` after 1 hour if needed.
