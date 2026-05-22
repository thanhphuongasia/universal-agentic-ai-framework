# ryuu-storage-jsonl

Append-only JSONL `ICollectionStore` implementation. File-per-scope layout — same approach OpenClaw uses for conversation logs.

## File scheme

```
<root>/<table>/<scope_key>.jsonl
```

Examples:

```
~/.ryuu/sessions/telegram_42.jsonl
~/.ryuu/memory_episodic/owner.jsonl
~/.ryuu/audit/2026-05-22.jsonl
```

Each line is one JSON-encoded item: `{"id": "...", "content": "...", "metadata": {...}, "created_at": ...}`. Append is atomic at the OS layer (single `write()` syscall, fsync optional).

## Why use this backend

- Append-mostly data (turns, observations, audit events): atomic, crash-safe, schema-flexible
- Easy debug: `tail -f ~/.ryuu/sessions/cli_local.jsonl`
- GDPR delete: `rm <scope>.jsonl` is instant and complete
- Per-scope file = no write contention between concurrent sessions
- Schema evolution: add fields freely; old readers ignore unknown keys

## When NOT to use this backend

- Frequent updates of same record (e.g. counters) → use `ryuu-storage-sqlite` `IKVStore`
- Need indexed search (`WHERE`, `ORDER BY`, joins) → use `ryuu-storage-sqlite` `ICollectionStore`
- Cross-scope aggregate queries (`SELECT SUM(cost) FROM all_users`) → SQLite or Postgres
- Vector / semantic similarity search → SQLite + `sqlite-vec`

See `docs/faq/faq_memory_storage.md` for the full SQLite vs JSONL decision matrix.

## Usage

```python
from ryuu_storage_jsonl import JsonlCollectionStore

store = JsonlCollectionStore(root_dir="~/.ryuu", table="memory_episodic")

# Append (atomic, crash-safe)
item_id = await store.append("owner", "User's name is Phuong", {"source": "intro"})

# List in time order
items = await store.list("owner", limit=10)

# Keyword search (naive linear scan)
results = await store.search("owner", "Phuong", top_k=3)

# Per-scope clear: rm the file
await store.clear("owner")
```

## Hybrid pattern

Combine with `SqliteCollectionStore` as an index sidecar — see `docs/faq/faq_memory_storage.md` "Hybrid pattern" section. JSONL is the durable source of truth; SQLite is a rebuildable index for fast queries.
