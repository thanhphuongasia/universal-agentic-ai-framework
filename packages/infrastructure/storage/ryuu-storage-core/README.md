# ryuu-storage-core

Storage protocols for the Ryuu framework. Zero implementation, zero dependencies — just contracts.

## Protocols

| Protocol | Access pattern | Use cases |
|----------|---------------|-----------|
| `IKVStore` | key → JSON value | sessions, settings, todos, prefs |
| `ICollectionStore` | append + list + search per scope | memory entries, audit log, events |
| `IBlobStore` | bytes blob by key + signed URLs | attachments, embeddings, large files |

## Adapter packages

Install one or more backends:

| Package | Backends | Pulls in |
|---------|----------|----------|
| `ryuu-storage-memory` | In-memory dict (dev/tests) | — |
| `ryuu-storage-sqlite` | SQLite (single file, prod-lite) | stdlib only |
| `ryuu-storage-postgres` *(future)* | PostgreSQL | asyncpg |
| `ryuu-storage-redis` *(future)* | Redis | redis |
| `ryuu-storage-s3` *(future)* | AWS S3 (BlobStore) | boto3 |

## Usage

Consumer packages (`ryuu-messaging-core.KVSessionStore`, `ryuu-knowledge-memory.WorkingMemoryStore`, your `TodoStore`, etc.) take a Protocol in their constructor. Pick the backend at composition time:

```python
# Test: in-memory
from ryuu_storage_memory import InMemoryKVStore
sessions = KVSessionStore(kv=InMemoryKVStore(table="sessions"))

# Prod: SQLite
from ryuu_storage_sqlite import SqliteKVStore
sessions = KVSessionStore(kv=SqliteKVStore(db_path="~/.ryuu/store.db", table="sessions"))

# Cloud: Redis (future)
from ryuu_storage_redis import RedisKVStore
sessions = KVSessionStore(kv=RedisKVStore(url=os.environ["REDIS_URL"], table="sessions"))
```

The Protocol layer is what makes the swap painless.
