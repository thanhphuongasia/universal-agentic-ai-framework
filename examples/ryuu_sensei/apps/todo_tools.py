"""Todo app — async tools backed by IKVStore.

Design notes:
  • Store is keyed by `user_id` so multiple users in the same process don't
    collide (think: one bot, many Telegram users).
  • The current user_id lives in a contextvar set by `TodoHandler` around each
    agent.run() call — the LLM never needs to know or pass the user_id itself.
  • Store is `KVTodoStore` (any IKVStore backend). Default at module level is
    in-memory; main.py injects `SqliteKVStore` for persistence.
  • One KV key per user holds the whole list — fewer keys, atomic updates,
    fine for the per-user N typical in a personal todo app.
"""

from __future__ import annotations

import contextvars
import json
from dataclasses import asdict, dataclass, field

from ryuu_storage_core import IKVStore
from ryuu_storage_memory import InMemoryKVStore

# ---------------------------------------------------------------------------
# Current-user context — set by TodoHandler around each agent.run()
# ---------------------------------------------------------------------------

_current_user: contextvars.ContextVar[str] = contextvars.ContextVar(
    "ryuu_sensei.todo.current_user", default="anonymous"
)


def set_current_user(user_id: str) -> contextvars.Token[str]:
    return _current_user.set(user_id)


def reset_current_user(token: contextvars.Token[str]) -> None:
    _current_user.reset(token)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

@dataclass
class Todo:
    id: int
    text: str
    done: bool = False


@dataclass
class _UserBlob:
    next_id: int = 1
    items: list[Todo] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps({
            "next_id": self.next_id,
            "items": [asdict(t) for t in self.items],
        })

    @classmethod
    def from_json(cls, blob: str) -> "_UserBlob":
        d = json.loads(blob)
        return cls(
            next_id=int(d.get("next_id", 1)),
            items=[Todo(**t) for t in d.get("items", [])],
        )


@dataclass
class KVTodoStore:
    """Persists per-user todo lists via any IKVStore (memory, SQLite, …).

    Schema: one KV key per user (e.g. 'user:42'); value is a JSON blob holding
    {next_id, items}. Simpler than per-todo keys, atomic mutations.
    """
    kv: IKVStore

    async def _load(self, user_id: str) -> _UserBlob:
        blob = await self.kv.get(f"user:{user_id}")
        if blob is None:
            return _UserBlob()
        try:
            return _UserBlob.from_json(blob)
        except (json.JSONDecodeError, KeyError):
            return _UserBlob()

    async def _save(self, user_id: str, blob: _UserBlob) -> None:
        await self.kv.put(f"user:{user_id}", blob.to_json())

    async def add(self, user_id: str, text: str) -> Todo:
        blob = await self._load(user_id)
        todo = Todo(id=blob.next_id, text=text)
        blob.next_id += 1
        blob.items.append(todo)
        await self._save(user_id, blob)
        return todo

    async def list(self, user_id: str) -> list[Todo]:
        blob = await self._load(user_id)
        return list(blob.items)

    async def complete(self, user_id: str, todo_id: int) -> Todo | None:
        blob = await self._load(user_id)
        for t in blob.items:
            if t.id == todo_id:
                t.done = True
                await self._save(user_id, blob)
                return t
        return None

    async def delete(self, user_id: str, todo_id: int) -> bool:
        blob = await self._load(user_id)
        before = len(blob.items)
        blob.items = [t for t in blob.items if t.id != todo_id]
        if len(blob.items) == before:
            return False
        await self._save(user_id, blob)
        return True


# Module-level store, defaults to in-memory. main.py swaps it via set_store().
STORE: KVTodoStore = KVTodoStore(kv=InMemoryKVStore(table="todos"))


def set_store(store: KVTodoStore) -> None:
    """Inject a different KVTodoStore (e.g. SQLite-backed) at app boot."""
    global STORE
    STORE = store


# ---------------------------------------------------------------------------
# Tools — async because the underlying IKVStore is async
# ---------------------------------------------------------------------------

async def add_todo(text: str) -> str:
    """Add a new todo item with the given description.

    Args:
        text: Short description of what needs to be done.

    Returns:
        A confirmation string including the new todo's ID.
    """
    user = _current_user.get()
    todo = await STORE.add(user, text)
    return f"Added todo #{todo.id}: {todo.text}"


async def list_todos() -> str:
    """List all todos for the current user, marking done vs open.

    Returns:
        A human-readable string. Empty list returns "No todos yet."
    """
    user = _current_user.get()
    items = await STORE.list(user)
    if not items:
        return "No todos yet."
    lines = []
    for t in items:
        mark = "x" if t.done else " "
        lines.append(f"[{mark}] #{t.id} {t.text}")
    return "Your todos:\n" + "\n".join(lines)


async def complete_todo(todo_id: int) -> str:
    """Mark a todo as completed.

    Args:
        todo_id: The numeric ID of the todo (shown in list_todos).

    Returns:
        Confirmation or 'not found' message.
    """
    user = _current_user.get()
    todo = await STORE.complete(user, todo_id)
    if todo is None:
        return f"Todo #{todo_id} not found."
    return f"Marked todo #{todo.id} as done: {todo.text}"


async def delete_todo(todo_id: int) -> str:
    """Delete a todo permanently.

    Args:
        todo_id: The numeric ID of the todo (shown in list_todos).

    Returns:
        Confirmation or 'not found' message.
    """
    user = _current_user.get()
    if await STORE.delete(user, todo_id):
        return f"Deleted todo #{todo_id}."
    return f"Todo #{todo_id} not found."


# Exported for convenient wiring: `Agent(tools=TODO_TOOLS)`
TODO_TOOLS = [add_todo, list_todos, complete_todo, delete_todo]


# Keep the old name available for external imports (backward-compat for
# anyone who imports `TodoStore` directly).
TodoStore = KVTodoStore
