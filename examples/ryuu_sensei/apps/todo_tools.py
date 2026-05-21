"""Todo app — minimal in-memory store + 4 tool functions.

Design notes:
  • Store is keyed by user_id so multiple users in the same process don't
    collide (think: one bot, many Telegram users).
  • The current user_id lives in a contextvar set by `TodoSensei` around each
    agent.run() call — the LLM never needs to know or pass the user_id itself.
    Tools read it from the contextvar. This keeps tool signatures clean.
  • Tools are plain sync functions with docstrings + type hints. ryuu.Agent's
    factory auto-builds the JSON-schema for tool calls. Sync and async tools
    are both supported by `_CallableWrapper.execute`.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Current-user context — set by TodoSensei around each agent.run()
# ---------------------------------------------------------------------------

_current_user: contextvars.ContextVar[str] = contextvars.ContextVar(
    "ryuu_sensei.todo.current_user", default="anonymous"
)


def set_current_user(user_id: str) -> contextvars.Token[str]:
    """Bind the user_id tools will see for the next agent.run() call."""
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
class TodoStore:
    """Per-user in-memory todo list. Swap for SQLite / KV store in real use."""
    _next_id: int = 1
    _items: dict[str, dict[int, Todo]] = field(default_factory=dict)

    def _bucket(self, user_id: str) -> dict[int, Todo]:
        return self._items.setdefault(user_id, {})

    def add(self, user_id: str, text: str) -> Todo:
        todo = Todo(id=self._next_id, text=text)
        self._next_id += 1
        self._bucket(user_id)[todo.id] = todo
        return todo

    def list(self, user_id: str) -> list[Todo]:
        return list(self._bucket(user_id).values())

    def complete(self, user_id: str, todo_id: int) -> Todo | None:
        todo = self._bucket(user_id).get(todo_id)
        if todo is None:
            return None
        todo.done = True
        return todo

    def delete(self, user_id: str, todo_id: int) -> bool:
        return self._bucket(user_id).pop(todo_id, None) is not None


# Singleton store for the demo. In a real app you would inject this.
STORE = TodoStore()


# ---------------------------------------------------------------------------
# Tools — what ryuu.Agent calls. Plain functions, no framework imports.
# ---------------------------------------------------------------------------

def add_todo(text: str) -> str:
    """Add a new todo item with the given description.

    Args:
        text: Short description of what needs to be done.

    Returns:
        A confirmation string including the new todo's ID.
    """
    user = _current_user.get()
    todo = STORE.add(user, text)
    return f"Added todo #{todo.id}: {todo.text}"


def list_todos() -> str:
    """List all todos for the current user, marking done vs open.

    Returns:
        A human-readable string. Empty list returns "No todos yet."
    """
    user = _current_user.get()
    items = STORE.list(user)
    if not items:
        return "No todos yet."
    lines = []
    for t in items:
        mark = "x" if t.done else " "
        lines.append(f"[{mark}] #{t.id} {t.text}")
    return "Your todos:\n" + "\n".join(lines)


def complete_todo(todo_id: int) -> str:
    """Mark a todo as completed.

    Args:
        todo_id: The numeric ID of the todo (shown in list_todos).

    Returns:
        Confirmation or 'not found' message.
    """
    user = _current_user.get()
    todo = STORE.complete(user, todo_id)
    if todo is None:
        return f"Todo #{todo_id} not found."
    return f"Marked todo #{todo.id} as done: {todo.text}"


def delete_todo(todo_id: int) -> str:
    """Delete a todo permanently.

    Args:
        todo_id: The numeric ID of the todo (shown in list_todos).

    Returns:
        Confirmation or 'not found' message.
    """
    user = _current_user.get()
    if STORE.delete(user, todo_id):
        return f"Deleted todo #{todo_id}."
    return f"Todo #{todo_id} not found."


# Exported for convenient wiring: `Agent(tools=TODO_TOOLS)`
TODO_TOOLS = [add_todo, list_todos, complete_todo, delete_todo]
