# ryuu-storage-postgres

PostgreSQL IKVStore + ICollectionStore backend for the ryuu framework.

## Usage

```python
from ryuu_storage_postgres import PostgresKVStore, PostgresCollectionStore

kv = PostgresKVStore(dsn="postgresql://user:pass@localhost/db", table="sessions")
coll = PostgresCollectionStore(dsn="postgresql://user:pass@localhost/db", table="episodic")
```

