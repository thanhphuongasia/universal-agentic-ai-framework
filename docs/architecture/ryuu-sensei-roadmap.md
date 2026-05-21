# Ryuu Sensei — Roadmap

Companion to [`ryuu-sensei-design.md`](./ryuu-sensei-design.md). This is the **execution plan** in phases.

---

## Phase 8.8 — `uaaf-mcp` Foundation (1–2 days)

**Goal:** make each domain app (todo, anki, stock) deployable as an MCP server, and let any Ryuu agent talk to MCP servers as a client.

- [ ] Create `packages/uaaf-mcp/` standalone package
- [ ] `MCPClient` — wrap the official `mcp` Python SDK, convert MCP tools → Ryuu `ToolRegistry`
- [ ] `MCPServer` — convert a Ryuu `BaseAgent` / `LLMAgent` + tools into an MCP server
- [ ] Convert `examples/todo_app` → exposes `todo-app-mcp` server
- [ ] Isolation test (fresh venv, install just `uaaf-mcp`, verify import works)
- [ ] CI job for `uaaf-mcp`

**Exit criteria:** `uvx ryuu-todo-mcp` runs a Todo MCP server. Any MCP client (e.g. Claude Desktop) can list its tools and call them.

---

## Phase 9.1 — Sensei Core (Channel + Gateway)  (2 days)

**Goal:** channel-agnostic core that any channel adapter can plug into. Working CLI adapter as test harness.

- [ ] `examples/ryuu_sensei/` skeleton (the sample built first, before the package extraction)
- [ ] `IncomingMessage` / `OutgoingMessage` canonical types
- [ ] `IChannelAdapter` protocol
- [ ] `SessionKey` = `f"{channel}:{user_id}"` enforced at every memory write
- [ ] `RyuuSensei` orchestrator class — channel-agnostic
- [ ] `CLIAdapter` (works out of the box, no external deps)
- [ ] Stub `TelegramAdapter` (interface ready, `aiogram` optional)
- [ ] Smoke test: CLI conversation persists across turns

**Exit criteria:** `python -m examples.ryuu_sensei.main` starts a CLI assistant that remembers prior turns.

---

## Phase 9.2 — Telegram Channel + HITL  (1–2 days)

**Goal:** first real network channel + safety gate.

- [ ] Add `aiogram` (or `python-telegram-bot`) dependency
- [ ] Implement `TelegramAdapter`:
  - polling mode for dev, webhook mode flag for prod
  - MarkdownV2 formatter (handle escaping)
  - typing indicator, error messages
  - basic commands: `/start`, `/help`, `/clear`
- [ ] Human-in-the-loop gate:
  - tool registry annotates risky tools (`risk_level: "high"`)
  - gate intercepts → sends "Approve? [Yes/No]" to user
  - resumes ReAct loop on approval
- [ ] Test: live Telegram chat → `@TodoBot` adds task via MCP → reply

**Exit criteria:** real Telegram bot answers messages and asks approval before risky actions.

---

## Phase 9.3 — Memory Substrate Upgrade  (2 days)

**Goal:** hybrid search + context compaction to survive long conversations.

- [ ] Hybrid search in `MemoryBackbone`:
  - vector: existing embedding pipeline
  - BM25: add `rank_bm25` dependency
  - final score = `w_v · vec + w_t · bm25` (config weights)
- [ ] LLM-based context compaction policy:
  - when KV-cache budget > 80% of model window, summarize oldest N turns
  - replace original turns with summary in conversation history
- [ ] JSONL append-only session log per `session_key`
- [ ] Test: 50-turn conversation stays under context budget

**Exit criteria:** assistant handles 50+ turns without context overflow.

---

## Phase 9.4 — Proactive Layer (Cron + Streaming)  (2 days)

- [ ] Cron-job scheduler (e.g. `apscheduler`)
- [ ] Proactive notification API:
  - `assistant.push(session_key, message)` → goes to right channel
- [ ] Example cron: "every morning at 9am, summarize portfolio for stock users"
- [ ] Token streaming through channel adapter (where supported)

**Exit criteria:** bot wakes up at scheduled time, pushes message to Telegram unprompted.

---

## Phase 9.5 — Slack + Discord  (1 day each)

- [ ] `SlackAdapter` — Block Kit formatter, webhook + signing secret verify
- [ ] `DiscordAdapter` — slash commands + button interactions
- [ ] Each adapter ~100–150 LOC by copying TelegramAdapter pattern

---

## Phase 10 — Memory Hub Migration  (3 days)

**Goal:** unblock cross-app memory while keeping federated deployment.

- [ ] Design `uaaf-memory-hub` service: HTTP/gRPC API
- [ ] ACL model: scope tags + per-app read permissions
- [ ] Refactor existing bots (Todo, Anki, Stock) to read/write through hub instead of local memory
- [ ] Identity bridge: `master_user_id` ↔ `{telegram_id, slack_id, discord_id}`
- [ ] Test: TodoBot can read Anki digest if user grants permission

**Exit criteria:** TodoBot answers "I'm stressed about studying" with awareness of Anki state.

---

## Phase 11 — Gateway Bot (Hybrid Mode)  (2 days)

- [ ] `@RyuuSensei` Telegram bot — gateway across all MCP apps
- [ ] Intent router (LLM classification: query → which MCP app)
- [ ] Cross-app workflow examples:
  - "summarize anki today + create todos based on weakest topics"
  - "if portfolio is down >2%, postpone non-critical todos"
- [ ] Existing per-app bots stay live; user picks which to chat with

**Exit criteria:** user can complete a multi-app workflow in a single chat.

---

## Phase 12+ — Production Hardening (optional)

- [ ] Docker sandbox for shell tools (replace `subprocess`)
- [ ] WebSocket server mode (OpenClaw port-18789 style)
- [ ] Web UI (browser chat client)
- [ ] Telemetry: OpenTelemetry traces across channel → gateway → MCP
- [ ] Multi-tenant deployment

---

## Decisions Locked

| Question | Answer | Rationale |
|----------|--------|-----------|
| Process model | Pure asyncio (single process) for MVP | Simplest, can swap to WS later without API break |
| MCP-first vs channel-first | **MCP-first** (Phase 8.8 before 9.x) | Real pluggable apps from day one |
| Memory at MVP | SQLite + sentence-transformers (Phase 9.3) | OpenClaw-proven; can swap to Qdrant later |
| Deployment model at MVP | **Option A** (Federated bots) | Fastest demo. Migrate to Option C at Phase 10 |
| First app | **TodoBot** | Most mature example, simplest business logic |
| Memory scope | Per-user (Telegram `user_id` is already global) | Group-chat shared memory deferred |
| HITL triggers | File delete, money transfer, shell exec, external API writes | Anything irreversible or with cost |

---

## Quick Reference — Where to start today

1. Read `examples/ryuu_sensei/README.md` — see the sample
2. Run `python -m examples.ryuu_sensei.main` — CLI assistant works immediately
3. Set `TELEGRAM_BOT_TOKEN` + `pip install aiogram` → Telegram works
4. Build Phase 8.8 (`uaaf-mcp`) next to unlock real MCP apps
