# ryuu-storage-sqlite

SQLite-backed `IKVStore` and `ICollectionStore`. Built on stdlib `sqlite3` wrapped in `asyncio.to_thread`. Zero external dependencies.

## Properties

- Single file DB — backup is `cp store.db backup.db`
- ACID transactions via SQLite WAL mode
- Single writer (fine for one bot process)
- Good up to ~100GB / millions of rows
- For multi-writer / network access → swap to `ryuu-storage-postgres` (future)

## Usage

```python
from ryuu_storage_sqlite import SqliteKVStore, SqliteCollectionStore

kv = SqliteKVStore(db_path="~/.ryuu/store.db", table="sessions")
await kv.put("user-42", '{"prefs": {...}}')
value = await kv.get("user-42")

coll = SqliteCollectionStore(db_path="~/.ryuu/store.db", table="memory_episodic")
item_id = await coll.append("scope-A", "Hello world", {"source": "chat"})
items = await coll.list("scope-A", limit=10)
```

Multiple stores can share one DB file by using different `table` names.
