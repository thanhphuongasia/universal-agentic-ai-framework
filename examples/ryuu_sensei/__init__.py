"""Ryuu Sensei — sample assistant on top of ryuu-messaging-* packages.

After Phase 8.8 refactor, channel/session/conversation primitives live in
their own PyPI packages:
  • ryuu-messaging-core     — protocols + ConversationManager + ChannelOrchestrator
  • ryuu-messaging-cli      — CLIAdapter
  • ryuu-messaging-telegram — TelegramAdapter

This sample is now just:
  • apps/todo_tools.py      — domain tools (sync functions + per-user contextvar)
  • apps/todo_handler.py    — TodoHandler (IChannelHandler impl)
  • main.py                 — wires the 4 moving parts together
"""

from examples.ryuu_sensei.apps.todo_handler import (
    ALLOWED_MODELS,
    TODO_INSTRUCTIONS,
    SessionStats,
    TodoHandler,
    TraceCapture,
    UserSettings,
)
from examples.ryuu_sensei.apps.todo_tools import (
    STORE,
    TODO_TOOLS,
    Todo,
    TodoStore,
    add_todo,
    complete_todo,
    delete_todo,
    list_todos,
    reset_current_user,
    set_current_user,
)

__all__ = [
    "ALLOWED_MODELS",
    "STORE",
    "SessionStats",
    "TODO_INSTRUCTIONS",
    "TODO_TOOLS",
    "Todo",
    "TodoHandler",
    "TodoStore",
    "TraceCapture",
    "UserSettings",
    "add_todo",
    "complete_todo",
    "delete_todo",
    "list_todos",
    "reset_current_user",
    "set_current_user",
]
