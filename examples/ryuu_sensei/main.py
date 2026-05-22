"""Ryuu Sensei demo — entry point.

This is the **wiring layer**. The four moving parts come from separate packages:

    ryuu_messaging_telegram.TelegramAdapter   ← Layer 1 (transport)
    ryuu_messaging_cli.CLIAdapter             ← Layer 1 (transport)
                  ↓
    ryuu_messaging_core.ChannelOrchestrator
                  ↓ (per message)
    ryuu_messaging_core.ConversationManager   ← Layer 2 (sessions + scope)
                  ↓
    examples.ryuu_sensei.apps.TodoHandler     ← Layer 3 (product logic)
                  ↓
    ryuu.Agent + apps.todo_tools.TODO_TOOLS   ← LLM + tools

Run modes:
  python -m examples.ryuu_sensei.main                # CLI only (default)
  python -m examples.ryuu_sensei.main --telegram     # CLI + Telegram
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from ryuu_messaging_cli import CLIAdapter
from ryuu_messaging_core import (
    ChannelOrchestrator,
    ConversationManager,
    DefaultScopeResolver,
    KVSessionStore,
)
from ryuu_storage_sqlite import SqliteKVStore

from examples.ryuu_sensei.apps import todo_tools
from examples.ryuu_sensei.apps.todo_handler import ALLOWED_MODELS, TodoHandler


# Default location for the sample's SQLite store. Overridable via env var.
DEFAULT_DB_PATH = Path(os.getenv("RYUU_SENSEI_DB", str(Path.home() / ".ryuu_sensei" / "store.db")))


# ---------------------------------------------------------------------------
# Slash-command callbacks — resolve scope through CM before mutating handler
# state, so /clear etc. respect the active IScopeResolver.
# ---------------------------------------------------------------------------

def _build_telegram_callbacks(
    orchestrator: ChannelOrchestrator,
    handler: TodoHandler,
    cm: ConversationManager,
):
    """Closures that bridge raw Telegram IDs → scope_key → handler state."""

    async def on_clear(sender_id: str, conversation_id: str) -> None:
        scope = await orchestrator.clear_scope("telegram", sender_id, conversation_id)
        await handler.reset_scope(scope)

    async def on_verbose(sender_id: str, conversation_id: str, on: bool) -> str:
        scope = await cm.resolve_scope("telegram", sender_id, conversation_id)
        await handler.set_verbose(scope, on)
        return f"Verbose is now **{'on' if on else 'off'}**."

    async def on_model(sender_id: str, conversation_id: str, model: str) -> str:
        scope = await cm.resolve_scope("telegram", sender_id, conversation_id)
        s = await handler.set_model(scope, model)
        return f"Model switched to **{s.model}**."

    async def on_settings(sender_id: str, conversation_id: str) -> str:
        scope = await cm.resolve_scope("telegram", sender_id, conversation_id)
        await handler._load_state(scope)
        s = handler.get_settings(scope)
        return (
            "⚙️ Settings\n"
            f"  • model:   {s.model}\n"
            f"  • verbose: {'on' if s.verbose else 'off'}\n\n"
            f"Allowed models: {', '.join(ALLOWED_MODELS)}\n"
            "Change via /model (tap to switch) or /verbose on|off"
        )

    async def on_status(sender_id: str, conversation_id: str) -> str:
        scope = await cm.resolve_scope("telegram", sender_id, conversation_id)
        await handler._load_state(scope)
        s = handler.get_settings(scope)
        stats = handler.get_stats(scope)
        session = await cm.session_store.load_or_create(
            scope_key=scope, channel="telegram",
            sender_id=sender_id, conversation_id=conversation_id,
        )
        return (
            "📊 Session status\n"
            f"  • model:           {s.model}\n"
            f"  • verbose:         {'on' if s.verbose else 'off'}\n"
            f"  • context buffer:  {len(session.history)} / {session.max_turns} turns\n"
            f"  • LLM calls:       {stats.turns}\n"
            f"  • tokens in/out:   {stats.input_tokens:,} / {stats.output_tokens:,}"
            f" (total {stats.input_tokens + stats.output_tokens:,})\n"
            f"  • cost so far:     ${stats.total_usd:.6f}"
        )

    async def on_current_model(sender_id: str, conversation_id: str) -> str:
        scope = await cm.resolve_scope("telegram", sender_id, conversation_id)
        await handler._load_state(scope)
        return handler.get_settings(scope).model

    return {
        "on_clear": on_clear,
        "on_verbose": on_verbose,
        "on_model": on_model,
        "on_settings": on_settings,
        "on_status": on_status,
        "on_current_model": on_current_model,
    }


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

async def run(use_telegram: bool) -> None:
    if not os.getenv("OPENAI_API_KEY"):
        print(
            "[ryuu-sensei] ⚠️  OPENAI_API_KEY not set. "
            "Tools won't fire with the fake provider — set the key for the full demo.\n"
        )

    # Layer 2 — channel-agnostic conversation management.
    # Sessions and todos share one SQLite file (~/.ryuu_sensei/store.db by
    # default; override with RYUU_SENSEI_DB env var). Multiple stores, one
    # DB file, distinct table names → easy backup, single source of truth.
    print(f"[ryuu-sensei] Using SQLite store: {DEFAULT_DB_PATH}")
    cm = ConversationManager(
        session_store=KVSessionStore(
            kv=SqliteKVStore(db_path=DEFAULT_DB_PATH, table="sessions"),
            max_turns=20,
        ),
        scope_resolver=DefaultScopeResolver(),   # per-sender, multi-tenant
    )

    # Wire the todo store to use SQLite too (same DB file, different table).
    # NOTE: In production this is REPLACED by an MCP call to a separate
    # Todo Pro service — todos are domain entities, not Sensei memory.
    # The in-process KVTodoStore here is a sample shortcut only.
    todo_tools.set_store(todo_tools.KVTodoStore(
        kv=SqliteKVStore(db_path=DEFAULT_DB_PATH, table="todos"),
    ))

    # Layer 3 — product logic. Persist handler state (settings + stats per
    # scope) through SQLite so /model and /verbose choices survive restarts.
    handler = TodoHandler(
        state_store=SqliteKVStore(db_path=DEFAULT_DB_PATH, table="handler_state"),
    )

    # Top-level orchestrator wires it all together
    orch = ChannelOrchestrator(conversation_manager=cm, handler=handler)
    orch.register_channel(CLIAdapter())

    if use_telegram:
        from ryuu_messaging_telegram import TelegramAdapter
        cbs = _build_telegram_callbacks(orch, handler, cm)
        tg = TelegramAdapter(
            on_clear=cbs["on_clear"],
            on_verbose=cbs["on_verbose"],
            on_model=cbs["on_model"],
            on_settings=cbs["on_settings"],
            on_status=cbs["on_status"],
            on_current_model=cbs["on_current_model"],
            allowed_models=ALLOWED_MODELS,
            welcome_text=(
                "Konnichiwa! I am Ryuu Sensei (流先生).\n\n"
                "I can help you manage todos. Try:\n"
                "  • add a todo: buy milk\n"
                "  • show my list\n"
                "  • mark #1 done\n\n"
                "Commands: /help  /status  /clear"
            ),
        )
        orch.register_channel(tg)

    try:
        await orch.start()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await orch.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description="Ryuu Sensei — todo demo")
    parser.add_argument(
        "--telegram",
        action="store_true",
        help="Also start the Telegram adapter (requires aiogram + TELEGRAM_BOT_TOKEN)",
    )
    args = parser.parse_args()
    try:
        asyncio.run(run(use_telegram=args.telegram))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
