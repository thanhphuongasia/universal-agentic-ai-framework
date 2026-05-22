# FAQ — Memory & Storage: SQLite vs JSONL files

> When does Ryuu Sensei (or any Ryuu-based product) store data in SQLite, and when in append-only JSONL files? Why does the framework ship both backends?

---

## TL;DR

| Data shape | Backend | Why |
|------------|---------|-----|
| **Conversation history** (turns) | JSONL | Append-mostly, audit-critical, easy GDPR delete |
| **Memory observations** (knowledge about user) | JSONL | Immutable, time-ordered, replayable |
| **Audit log** (cost / tool calls / events) | JSONL | Compliance hash chain — never overwrite |
| **Session metadata** (last seen, scope keys) | SQLite (KV) | Mutable, frequent updates |
| **User settings** (model choice, verbose flag) | SQLite (KV) | Small mutable state, fast lookup |
| **Stats** (turn count, token totals, $ cost) | SQLite (KV) | Mutable counters, no history needed |
| **Domain entities** (todos, cards, portfolios) | **Domain product's own DB** — NOT Sensei | Sensei calls product via MCP; product owns its data |
| **Vector index** for semantic search (Phase 9.3+) | SQLite + `sqlite-vec` | Indexed nearest-neighbor |

**Rule of thumb**: if you'd ever want to `grep` or `tail -f` the file → JSONL. If you'd ever want to `WHERE / ORDER BY` → SQLite.

---

## Why two backends, not one?

Different data has different access patterns. Forcing one backend creates pain:

- **Forcing SQLite on append-mostly history**: schema migrations every time you add a field; binary format hostile to `grep`; per-scope GDPR delete leaves dead rows until `VACUUM`.
- **Forcing JSONL on mutable settings**: every `/verbose on` rewrites a multi-MB file; no atomic update; querying "what model is user X on?" requires a full scan.

The framework ships `ryuu-storage-core` (Protocols) + `ryuu-storage-sqlite` + `ryuu-storage-jsonl` separately. Pick per data type at composition time.

---

## Tradeoff matrix

| Aspect | **SQLite** | **JSONL files** |
|--------|-----------|----------------|
| **Crash safety** | WAL mode OK; corruption rare but nasty | ✅ Atomic append. Partial line = drop, rest sống |
| **Schema evolution** | Migration scripts mandatory; backfill cost | ✅ Add new field, old readers ignore. Forward + backward compat free |
| **Cross-scope queries** | ✅ `WHERE scope IN (...)` đơn giản | ❌ Glob + parse N files |
| **Per-scope deletion (GDPR)** | `DELETE WHERE scope_key=X` — DB còn dấu vết đến `VACUUM` | ✅ `rm session_<id>.jsonl` — instant + complete |
| **Indexing** | ✅ Built-in B-tree | ❌ Full scan (OS page cache cứu được recent files) |
| **Vector / FTS** | ✅ `sqlite-vec` extension, FTS5 | ❌ Native không có; cần sidecar (Qdrant, Tantivy) |
| **Human inspection** | `sqlite3 .db "SELECT * FROM x"` | ✅ `cat file.jsonl` / `grep` / `tail -f` / `jq` |
| **Backup** | Lock during WAL checkpoint hoặc `.backup` command | ✅ `cp -r ~/.ryuu/sessions/ backup/` |
| **Concurrent writers** | Single writer (WAL queues readers) | ✅ Per-scope file = N writers concurrent |
| **Storage size** | ✅ Compact binary, indexed | ❌ JSON verbose (`gzip` optional cho cold files) |
| **Read performance** | ✅ Indexed = O(log n) lookup | OS page cache giúp recent reads; cold scan = O(n) |
| **Bad-state recovery** | `.recover` command; corruption nasty | ✅ Bad line → drop, rest sống |
| **Toolchain** | sqlite3 CLI, DB Browser GUI | `less`, `jq`, `tail -f`, any editor |
| **Multi-process safety** | ⚠️ Hot path locking issues | ✅ File-per-scope = no contention |
| **Streaming append** | ❌ `INSERT` per row, transaction overhead | ✅ One write syscall, append-only |

---

## Conceptual diff

### SQLite = relational DB approach
- "State = rows in table, mutable, indexed"
- Tốt khi cần `SELECT/JOIN/aggregate`
- Schema = contract, breaking change costly

### JSONL = event-log approach
- "State = derived by replaying append-only events"
- Tốt khi history matters (audit, replay, debug)
- Schema = evolving, additive only

Same pattern as: Kafka topics (JSONL-ish) feed Elasticsearch index (SQLite-ish). Postgres WAL feeds replicas. Event sourcing systems.

---

## Concrete data examples for Ryuu Sensei

### ✅ JSONL: Conversation turns

```jsonl
{"ts": 1716326400.1, "role": "user", "text": "add: buy milk"}
{"ts": 1716326400.5, "role": "assistant", "text": "Added todo #1: buy milk"}
{"ts": 1716326500.2, "role": "user", "text": "what's on my list?"}
{"ts": 1716326500.8, "role": "assistant", "text": "1. [ ] buy milk"}
```

- Append-only: a turn happened, you never edit it
- Time-ordered: read top-to-bottom = chronological
- Easy to debug: `tail -f sessions/telegram_42.jsonl` while testing
- GDPR delete: `rm sessions/telegram_42.jsonl` → user X's data gone, instant + complete

### ✅ JSONL: Memory observations (knowledge about user)

```jsonl
{"ts": 1716326400.0, "content": "User's name is Phuong"}
{"ts": 1716330000.0, "content": "Prefers gpt-4o for complex tasks"}
{"ts": 1716333600.0, "content": "Working on UAAF framework refactor"}
{"ts": 1716340000.0, "content": "Lives in Tokyo (gathered from timezone)"}
```

- Each observation is a fact-at-a-point-in-time
- Never deleted — newer observations supersede via assembler logic
- Replay: rebuild user profile by reading file top-to-bottom

### ✅ JSONL: Audit log (compliance + debug)

```jsonl
{"ts": ..., "event": "tool_call", "tool": "add_todo", "args": {"text": "..."}, "user_id": "...", "cost_usd": 0.0001, "prev_hash": "abc...", "hash": "def..."}
{"ts": ..., "event": "llm_call", "model": "gpt-4o-mini", "tokens_in": 234, "tokens_out": 56, "cost_usd": 0.00007, "prev_hash": "def...", "hash": "ghi..."}
```

- Hash chain: each entry includes hash of previous → tamper-proof
- Append-only is structural: an audit log you can rewrite isn't an audit log

### ✅ SQLite: Session metadata (mutable KV)

```sql
SELECT key, value FROM sessions WHERE key = 'telegram:42';
-- {"scope_key": "telegram:42", "channel": "telegram", "last_seen": 1716340000, ...}
```

- Small, frequent updates (every turn touches `last_seen`)
- KV lookup by scope_key
- JSON value carries the mutable bits; the history itself lives in JSONL

### ✅ SQLite: User settings

```sql
SELECT key, value FROM handler_state WHERE key = 'telegram:42';
-- {"model": "gpt-4o", "verbose": true, "language": "vi"}
```

- Small data, by-key access pattern
- Frequent reads (every message), occasional writes (`/model`, `/verbose`)
- JSONL would be silly: append a new "settings" line every `/verbose on`? No.

### ✅ SQLite: Running stats

```sql
SELECT key, value FROM stats WHERE key = 'telegram:42';
-- {"turns": 47, "tokens_in": 12340, "tokens_out": 3456, "total_usd": 0.034}
```

- Pure counters, monotonically increasing
- Update every turn → `UPDATE` is right verb

### ❌ NOT in Sensei at all: Domain entities

```python
# Don't do this in Sensei:
KVTodoStore(kv=SqliteKVStore("~/.ryuu_sensei/store.db", "todos"))   # WRONG for prod

# Do this:
class TodoHandler(IChannelHandler):
    async def handle(self, msg, session):
        result = await self.mcp_client.call("todo-pro", "create_task", {"text": msg.text})
        return OutgoingMessage(text=f"Added task #{result.task_id}")
```

- Todo Pro owns its database (its own SQLite / Postgres)
- Sensei calls Todo Pro via MCP — just passes the request through
- Todo Pro can be deployed independently, multi-tenant, scaled separately

---

## Hybrid pattern (advanced — Phase 9.3+)

For semantic memory at scale: JSONL = source of truth + SQLite = derived index.

```
Write path:
    handler.write(observation)
        → JSONL append (atomic, durable)
        → SQLite INSERT into index (best-effort, rebuildable)

Read path:
    handler.search(query)
        → SQLite FTS / vector lookup → top_k row pointers
        → fetch full content from JSONL (or cache in SQLite payload)

Recovery path:
    if SQLite index missing/corrupt at boot:
        scan JSONL → rebuild index → resume
```

Same pattern as:
- Elasticsearch: Lucene segments (binary index) + translog (append-only)
- Kafka Streams: state stores + changelog topic
- Postgres replicas: WAL stream + materialized view

The framework will provide this as `HybridMemoryStore` (Phase 9.3) — opaque from handler's POV, just an `ICollectionStore` impl that does both writes internally.

---

## When you don't know, start with JSONL

Cheap to migrate JSONL → SQLite later (just write a one-time importer). Going the other way (SQLite → JSONL) needs schema introspection and CSV-dump gymnastics. **Default to JSONL for anything observation-shaped**, escalate to SQLite when query patterns demand it.

---

## See also

- `docs/architecture/OpenClaw_Architecture_Deep_Dive.md` — OpenClaw uses JSONL exclusively for conversation logs
- `docs/architecture/ryuu-sensei-design.md` — overall architecture
- `packages/infrastructure/storage/ryuu-storage-core/README.md` — Protocol surface
- `packages/infrastructure/storage/ryuu-storage-jsonl/README.md` — JSONL backend
- `packages/infrastructure/storage/ryuu-storage-sqlite/README.md` — SQLite backend
