# Ryuu Sensei — Multi-Channel AI Assistant Architecture

> **"Sensei" (先生)** = teacher/master in Japanese. Ryuu Sensei = the assistant tier on top of the Ryuu (流) framework.

## 1. Mission

Build a **persistent, multi-channel AI assistant** on top of the Ryuu framework that can:

- Talk to users through chat channels (Telegram first, then Slack/Discord/Web/CLI)
- Compose multiple **domain apps** (Todo, Anki Flashcard, Stock Advisory, …) as pluggable units
- Share memory across apps when desirable, isolate when not
- Survive 24/7 (proactive cron alerts, not just request/response)

This document captures the **architectural analysis** behind the Ryuu Sensei design. Roadmap is in [`ryuu-sensei-roadmap.md`](./ryuu-sensei-roadmap.md).

---

## 2. Reference Architecture (OpenClaw 4-layer)

OpenClaw (see [`OpenClaw_Architecture_Deep_Dive.md`](./OpenClaw_Architecture_Deep_Dive.md)) gives us the load-bearing pattern. Ryuu Sensei adopts the 4 layers:

```
   [Telegram | Slack | Discord | CLI | Web]
                    │
                    ▼
   ┌───────────────────────────────────┐
   │ 1. Channel Layer                  │  IChannelAdapter
   │    normalize → canonical message  │  IncomingMessage / OutgoingMessage
   │    markdown dialect per platform  │
   └────────────────┬──────────────────┘
                    │ session_key = f"{channel}:{user_id}"
                    ▼
   ┌───────────────────────────────────┐
   │ 2. Gateway Control Plane          │  Persistent asyncio process
   │    session scoping (no leak)      │
   │    Human-in-the-loop gate         │
   │    Cron jobs (proactive push)     │
   │    Auth / rate-limit per session  │
   └────────────────┬──────────────────┘
                    │
                    ▼
   ┌───────────────────────────────────┐
   │ 3. Agent Runtime                  │  LLMAgent + ReAct loop (already in Ryuu)
   │    intent router → MCP app        │  + LLM context compaction
   │    ReAct loop                     │  + Token streaming
   └────────────────┬──────────────────┘
                    │
                    ▼
   ┌───────────────────────────────────┐
   │ 4. Memory & Tool Substrate        │
   │    hybrid search (vec + BM25)     │
   │    JSONL append-only logs         │
   │    Docker sandbox for tools       │
   │    MCP client adapter             │
   └───────────────────────────────────┘
```

### Mapping OpenClaw layers → Ryuu framework status

| OpenClaw Layer | Ryuu Status | Gap |
|----------------|-------------|-----|
| 1. Channel Layer | ❌ Not yet | `IChannelAdapter` + canonical message types |
| 2. Gateway Control Plane | ⚠️ Partial (`RequestHandler` from Phase 7) | persistent process, session scoping, cron, HITL |
| 3. Agent Runtime | ✅ Done — `LLMAgent + ReAct loop` | add LLM-based context compaction |
| 4. Memory & Tool Substrate | ⚠️ Partial — `MemoryBackbone` exists | hybrid search, Docker sandbox, MCP client |

---

## 3. Load-Bearing Decisions (Structural — do NOT change later)

These derive directly from OpenClaw's structural choices.

| Decision | Why load-bearing |
|----------|------------------|
| **Persistent process** (asyncio, not serverless) | Need warm state, WebSocket connections, cron triggers, proactive push |
| **Session key scoping** `channel:user_id` | Prevents cross-user / cross-channel data leak; every memory write/read MUST be keyed |
| **Delegated Agent Loop** | LLM reasoning must never know about Telegram/Slack APIs. Channel adapters convert; core stays agnostic |
| **Canonical message format** | One internal `IncomingMessage`/`OutgoingMessage` schema; channels translate at the boundary |

### Swappable (Pragmatic — can change later)

| Decision | Initial choice | Future option |
|----------|----------------|---------------|
| Memory storage | SQLite + sentence-transformers | Qdrant / Pinecone / Milvus |
| Tool sandbox | `subprocess` for MVP | Docker / gVisor / Firecracker |
| Channel UI | Markdown text | Rich blocks (Slack Block Kit, Telegram inline keyboards) |
| Vector model | OpenAI embeddings | Local sentence-transformers / Voyage |

---

## 4. Deployment Models — Tradeoff Analysis

The biggest design choice: **one bot per app**, or **one bot for all apps**?

### Option A — Federated Bots (1 bot per app)

```
@TodoBot     @AnkiBot     @StockBot
   │            │            │
 todo db     anki db      stock db    ← memory siloed
```

### Option B — Unified Bot (1 bot → many MCP apps)

```
        @RyuuBot
   ┌──────┼──────┐
   ▼      ▼      ▼
 todo   anki   stock     ← shared memory at gateway
```

### Option C — Federated + Shared Memory Hub ⭐ recommended target

```
@TodoBot   @AnkiBot   @StockBot
   │          │          │
   └──────────┼──────────┘
              ▼
      ┌───────────────┐
      │ Memory Hub    │   REST/gRPC service
      │ key: user_id  │   ACL: cross-app read permission
      └───────────────┘
```

### Option D — Hybrid (Federated + Gateway)

```
@TodoBot  @AnkiBot  @StockBot       @RyuuBot (gateway)
   │         │         │               │
   └─────────┼─────────┴───────────────┘
             ▼
       Memory Hub
```

User uses focused bots when working on one app; uses gateway bot for cross-app workflows.

### Tradeoff Matrix

| Criterion | A: Federated | B: Unified | C: Federated+Hub | D: Hybrid |
|-----------|--------------|------------|------------------|-----------|
| **Shared memory** | ❌ silo | ✅ native | ✅ via hub | ✅ via hub |
| **Cross-app workflow** | ❌ | ✅ | ⚠️ in-app code | ✅ at gateway |
| **Failure isolation** | ✅ | ❌ single point | ✅ apps independent | ✅ |
| **Deployment independence** | ✅ uvx install each | ❌ monorepo | ✅ per-bot deploy | ✅ |
| **UX (one chat vs many)** | ⚠️ user switches chats | ✅ one chat | ⚠️ switch | ✅ user picks mode |
| **Intent routing** | ✅ NOT needed (user chose bot) | ❌ must code router | ✅ not needed | ⚠️ only at gateway |
| **Permission / ACL** | ✅ scope is clear | ❌ must code | ✅ at hub | ⚠️ at hub + gateway |
| **Build complexity** | ✅ simplest | ⚠️ medium | ⚠️ +memory hub | ❌ most complex |
| **Cost tracking** | ❌ split | ✅ unified | ⚠️ split but aggregable | ✅ |
| **Proactive push** | ❌ each bot pushes | ✅ one source | ⚠️ each bot pushes | ✅ gateway pushes |
| **Distribution** | ✅ sell each | ❌ monolithic | ✅ | ⚠️ |
| **Time to first demo** | ✅ ~1 day | ⚠️ ~3 days | ❌ ~4 days | ❌ ~5+ days |

### Recovery strategies if Option A is chosen (memory silo problem)

1. **Memory Hub Service** ⭐ — standalone service all bots write to (this is Option C)
2. **Daily Digest Cron** — each bot dumps summary to shared storage end-of-day
3. **User Identity Bridge** — link `telegram_id`/`slack_id`/`discord_id` to `master_user_id`
4. **Inter-bot Event Bus** — Redis pub/sub, bots react to each other's events
5. **MCP-style Resources** — each bot exposes `/resource/digest` endpoint, peers query on demand

---

## 5. Staged Recommendation

| Stage | Model | Why |
|-------|-------|-----|
| **MVP (Phase 9)** | Option A — Federated | Fastest demo. Accept memory silo for now. Prove the pattern. |
| **Growth (Phase 10)** | Migrate to Option C | After 2–3 bots exist, build Memory Hub. Refactor bots to use it. |
| **Mature (Phase 11+)** | Option D — Hybrid | Add `@RyuuSensei` gateway bot for power users. Federated bots remain for focused use. |

---

## 6. Reusability Score (Channel adapters)

| Component | Reusable across channels? |
|-----------|---------------------------|
| Intent Router | ✅ 100% |
| Memory Backbone | ✅ 100% (key by `session_key`) |
| LLM + ReAct loop | ✅ 100% |
| MCP clients | ✅ 100% |
| Cost / Audit / Rate-limit | ✅ 100% |
| Channel adapter (telegram/slack/...) | ❌ Per-channel (~100–150 LOC each) |
| Message formatting | ⚠️ Adapter handles markdown dialect |
| Rich UI (buttons, blocks) | ⚠️ Adapter maps `Action` → native format |

**Net: ~90% code reuse**, each new channel is ~100–150 LOC.

---

## 7. Channel-specific Gotchas (for future channel adapters)

| Platform | Markdown dialect | Auth | Rich UI |
|----------|------------------|------|---------|
| **Telegram** | `MarkdownV2` (strict escaping) | `bot_token` | Inline keyboards, callback queries |
| **Slack** | `mrkdwn` (non-standard) | `bot_token` + `signing_secret` (verify webhook) | Block Kit |
| **Discord** | Standard markdown + custom | `bot_token` + intents | Buttons, select menus, slash commands |
| **CLI** | Plain text / ANSI | None | None |

Each adapter needs a `MessageFormatter` to render `OutgoingMessage` to the platform's dialect.

---

## 8. Open Design Questions

1. **Persistent process model:**
   - (a) Pure asyncio (single process) — simplest, recommended for dev
   - (b) WebSocket server (OpenClaw style, port 18789) — multi-client ready

2. **MCP-first or channel-first?**
   - (a) MCP foundation first → real pluggable apps
   - (b) Channel first with in-process tools → faster Telegram demo

3. **Memory storage at MVP:**
   - (a) SQLite + sentence-transformers (OpenClaw style)
   - (b) JSONL only (simplest, no vector search initially)

4. **HITL scope** — which tool categories require user approval?
   - File deletion, money transfer, shell execution, external API writes?

These are answered in the roadmap document, but kept here as the structural questions.
