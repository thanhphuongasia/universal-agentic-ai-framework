# Ryuu Sensei — Sample Project

> **"Sensei" (先生)** = teacher / master. Ryuu Sensei is the assistant tier on top of the Ryuu (流) framework.

This is the **first sample / skeleton** for the Ryuu Sensei assistant. It demonstrates the channel-agnostic core pattern (matches OpenClaw's 4-layer architecture) with a working CLI adapter and a Telegram adapter stub.

For the full architectural rationale see:
- [`docs/architecture/ryuu-sensei-design.md`](../../docs/architecture/ryuu-sensei-design.md) — analysis, tradeoffs, deployment models
- [`docs/architecture/ryuu-sensei-roadmap.md`](../../docs/architecture/ryuu-sensei-roadmap.md) — phased execution plan

---

## What's here

```
examples/ryuu_sensei/
├── README.md              # this file
├── __init__.py
├── messages.py            # IncomingMessage, OutgoingMessage, Action, Attachment
├── channel.py             # IChannelAdapter protocol
├── session.py             # SessionKey scoping, SessionStore (in-memory)
├── sensei.py              # RyuuSensei — channel-agnostic orchestrator
├── cli_adapter.py         # CLIAdapter — works out of the box
├── telegram_adapter.py    # TelegramAdapter — stub, requires aiogram
├── apps/
│   ├── todo_tools.py      # 4 tool functions (add/list/complete/delete) + TodoStore
│   └── todo_sensei.py     # TodoSensei(RyuuSensei) — wires user contextvar around agent.run
└── main.py                # demo entry point
```

The sample maps to OpenClaw's 4-layer model:

| Layer | Files |
|-------|-------|
| 1. Channel Layer | `channel.py` (protocol), `cli_adapter.py`, `telegram_adapter.py` |
| 2. Gateway Control Plane | `sensei.py` (session scoping, message routing) |
| 3. Agent Runtime | **delegated to `ryuu.Agent`** — ReAct loop + cost/audit/budget come from the framework |
| 4. Memory & Tool Substrate | `session.py` (short-term buffer); upgrade path = `MemoryBackbone` (Phase 9.3) |

The sample composes Ryuu — it does NOT reimplement the LLM loop, cost tracking, or audit. `RyuuSensei.handle_message()` calls `self.agent.run(message=..., user_id=..., session_id=...)` and the framework handles the rest.

---

## Run it

### CLI mode

```bash
export OPENAI_API_KEY=sk-...          # for real LLM responses
python -m examples.ryuu_sensei.main
```

Without `OPENAI_API_KEY`, `ryuu.Agent` falls back to its auto-detected fake provider — you can still drive the REPL, just with stub responses.

Example session (with key set) — tools fire end-to-end:

```
[ryuu-sensei] CLI started. Type 'exit' or Ctrl-D to quit.

you> add a todo: buy milk
sensei> I've added your todo: "buy milk" as todo #1.

you> add another: read book
sensei> I've added your todo: "read book" as todo #2.

you> show my todos
sensei> Here are your todos:
        1. [ ] buy milk
        2. [ ] read book

you> mark #1 done
sensei> I've marked todo #1 as done: "buy milk."

you> show my todos
sensei> 1. [x] buy milk
        2. [ ] read book
```

What's happening under the hood (turn on `verbose=True` in `main.py` to see it):

```
💭 Thought: I'll use add_todo to gather the data I need.
🔧 Action:      add_todo({"text": "buy milk"})
📋 Observation: "Added todo #1: buy milk"
✅ Final answer: I've added your todo: "buy milk" as todo #1.
```

ReAct loop, tool dispatch, cost tracking, audit, budget enforcement — all delegated to `ryuu.Agent`. The sensei only adds: channel routing, session scoping, and the contextvar that binds tools to the current user.

### Telegram mode

```bash
pip install 'aiogram>=3.0'

# 1) Create a bot:  open Telegram → @BotFather → /newbot → follow prompts.
#    BotFather replies with a token like: 1234567890:AAExxxxxxxxxxxxxxxxxxxxx
# 2) Export it. NEVER commit it. NEVER paste it into a code file.
export OPENAI_API_KEY='sk-...'
export TELEGRAM_BOT_TOKEN='123456:ABC...'

# 3) Run — CLI keeps working in this terminal, Telegram listens in parallel.
python -m examples.ryuu_sensei.main --telegram
```

Open the chat with your bot in Telegram and try:

```
/start         → welcome banner
add: buy milk  → sensei calls add_todo, replies "Added todo #1: buy milk"
show my list   → sensei calls list_todos
mark #1 done   → sensei calls complete_todo
/clear         → wipes this user's short-term conversation memory
/help          → command list
```

Both channels share the same `RyuuSensei` instance and the same `SessionStore`. Session keys are scoped per channel (`telegram:<user_id>` vs `cli:local`) so a CLI session and a Telegram session for the same user stay separate. Per-Telegram-user todos are isolated too via the user contextvar (`apps/todo_tools.py`).

#### Security checklist

- [ ] `.env` (containing the real token) is in `.gitignore` (already covered by the repo's root `.gitignore`)
- [ ] Never paste the token into Slack/chat/PR descriptions/code review tools
- [ ] If a token leaks: `@BotFather` → `/revoke` → choose your bot → new token issued
- [ ] In production: use a **webhook** (not polling) behind HTTPS and verify Telegram's `X-Telegram-Bot-Api-Secret-Token` header. Webhook mode is Phase 9.4 in the roadmap.

#### What this adapter does *not* do yet

| Missing | Phase |
|---------|-------|
| Webhook mode + signature verification | 9.4 |
| Human-in-the-loop approval for risky tools | 9.2 (HITL gate — separate task) |
| Inline keyboards / `OutgoingMessage.actions` rendering | 9.2 (UI polish) |
| File / image / voice attachment ingestion | 9.4 |
| Group-chat shared memory (currently per-user only) | 10 |

---

## Adding your own app

Pattern is 3 files (see `apps/todo_*` for the reference):

1. **`apps/<your_app>_tools.py`** — tool functions (sync or async, both work) + an in-memory store. Docstring's first line + type hints become the JSON-schema the LLM sees. Bind user scope through a `contextvars.ContextVar`, NOT a tool argument.
2. **`apps/<your_app>_sensei.py`** — subclass `RyuuSensei`, override `handle_message` to set the user contextvar around `super().handle_message(msg)`.
3. **`main.py`** — instantiate your sensei with `Agent(..., tools=YOUR_TOOLS)`.

### Tool API mode — when to upgrade beyond `tools=[callable]`

The sample uses **Mode A** (callable list, schema auto-built from docstring + type hints). It's the simplest and reads like normal Python — right tradeoff for a skeleton. The framework offers two more modes for when Mode A runs out of headroom:

| Symptom | Switch to |
|---------|-----------|
| Tool needs a DB connection / HTTP client / cache | **Mode C** — `tool_registry=build_my_registry(deps)` (closure DI; see `examples/todo_app/tools.py` for the pattern) |
| Multi-tenant: each org needs an isolated store | **Mode C** — one registry per tenant |
| Per-tool permissions (e.g. `delete_*` only for admins) | **Mode C** — `registry.register(name, fn, allowed_domains={...})` |
| Schema needs `Optional[X]` / `Union[A, B]` / nested objects | **Mode B** — implement `ITool` with an explicit `schema=` dict (the auto-introspector handles only `str/int/float/bool/list/dict`) |
| Tool will be exposed via MCP (Phase 8.8) | **Mode B** — MCP tools are class-based; maps 1:1 to `ITool` |

Mode A + a module-level store + a contextvar (what this sample does) covers everything **up to** the symptoms above. Don't pre-emptively migrate.

## Customize the Agent

The sensei builds a default `ryuu.Agent` with `gpt-4o-mini` if you don't pass one. To customize (different model, tools, budget, hooks, …):

```python
from ryuu import Agent
from examples.ryuu_sensei.sensei import RyuuSensei, DEFAULT_INSTRUCTIONS

agent = Agent(
    model="gpt-4o",                       # upgrade model
    instructions=DEFAULT_INSTRUCTIONS,
    tools=[my_tool_fn],                   # add tool-calling
    budget_usd=2.0,                       # per-session cap
    max_iterations=5,                     # ReAct loop rounds per .run()
)
sensei = RyuuSensei(agent=agent)
```

Everything `ryuu.Agent` supports — multi-provider fallback, YAML prompts, hooks, streaming — is yours for free. See `docs/guides/quickstart/01-factory.md`.

---

## Add a new channel

Implement `IChannelAdapter` (see `channel.py`). Reference: `cli_adapter.py` is ~80 LOC. A new channel adapter is typically 100–150 LOC.

```python
@dataclass
class MySlackAdapter(IChannelAdapter):
    channel_name: str = "slack"

    async def start(self, on_message):
        # 1. Listen on Slack events API
        # 2. For each event: translate → IncomingMessage
        # 3. await on_message(msg) → OutgoingMessage
        # 4. send reply via Slack API
        ...

    async def stop(self): ...
    async def send(self, msg): ...
    async def send_typing(self, conversation_id): ...
```

Then in `main.py`:

```python
sensei.register_channel(MySlackAdapter(...))
```

---

## What's intentionally NOT in this sample

This is a **skeleton**, not a finished assistant. The following are deferred to later roadmap phases:

| Missing | Roadmap phase | Note |
|---------|---------------|------|
| Real MCP client/server | Phase 8.8 | Sample uses a fake LLM; no actual tools |
| Hybrid memory search | Phase 9.3 | `SessionStore` is in-memory FIFO; swap for `MemoryBackbone` |
| LLM context compaction | Phase 9.3 | Buffer just drops oldest turns past `max_turns=20` |
| Human-in-the-loop gate | Phase 9.2 | No tool approval flow yet |
| Cron jobs / proactive push | Phase 9.4 | `RyuuSensei.push()` is wired but no scheduler |
| Memory Hub (cross-app shared memory) | Phase 10 | Each session is isolated |
| Gateway bot (multi-MCP routing) | Phase 11 | This sample is the per-app pattern (Option A — Federated) |

See `ryuu-sensei-roadmap.md` for the full breakdown.

---

## Design invariants — DO NOT break

These are the load-bearing decisions from OpenClaw's architecture review. Changing them later is expensive.

1. **`RyuuSensei` never imports a channel SDK.** All Telegram/Slack/Discord types stay inside their adapter files.
2. **Every memory write uses `make_session_key(channel, user_id)`.** Never hand-roll the key with f-strings — go through the helper to keep the scoping invariant intact.
3. **`IncomingMessage` / `OutgoingMessage` are the only types crossing the channel boundary.** Adapters translate at the edge; core stays canonical.
4. **The sensei is a persistent asyncio process, not request/response.** Channels keep their connections warm; cron jobs and proactive pushes depend on this.
