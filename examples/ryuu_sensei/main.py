"""Ryuu Sensei demo — entry point with todo tools.

Run modes:
  python -m examples.ryuu_sensei.main                # CLI only (default)
  python -m examples.ryuu_sensei.main --telegram     # CLI + Telegram (needs aiogram + token)

The sensei is wired with the Todo app's tools (`add_todo`, `list_todos`,
`complete_todo`, `delete_todo`). Try messages like:
  - "add todo: buy milk"
  - "what's on my list?"
  - "mark #1 done"
  - "delete #2"

LLM wiring:
  • OPENAI_API_KEY set → ryuu.Agent uses gpt-4o-mini for tool calls
  • Not set → fake provider; tool calls will not actually fire because the
    fake doesn't emit tool-call tokens. Set the key for the full demo.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from examples.ryuu_sensei.apps.todo_sensei import ALLOWED_MODELS, TodoSensei
from examples.ryuu_sensei.cli_adapter import CLIAdapter


def _format_settings(sensei: TodoSensei, channel: str, user_id: str) -> str:
    s = sensei.get_settings(channel, user_id)
    return (
        "⚙️ Settings\n"
        f"  • model:   {s.model}\n"
        f"  • verbose: {'on' if s.verbose else 'off'}\n\n"
        f"Allowed models: {', '.join(ALLOWED_MODELS)}\n"
        "Change via /model (tap to switch) or /verbose on|off"
    )


def _format_status(sensei: TodoSensei, channel: str, user_id: str) -> str:
    s = sensei.get_settings(channel, user_id)
    stats = sensei.get_stats(channel, user_id)
    ctx_turns = sensei.context_size(channel, user_id)
    return (
        "📊 Session status\n"
        f"  • model:           {s.model}\n"
        f"  • verbose:         {'on' if s.verbose else 'off'}\n"
        f"  • context buffer:  {ctx_turns} / {sensei.sessions.max_turns} turns\n"
        f"  • LLM calls:       {stats.turns}\n"
        f"  • tokens in/out:   {stats.input_tokens:,} / {stats.output_tokens:,}"
        f" (total {stats.input_tokens + stats.output_tokens:,})\n"
        f"  • cost so far:     ${stats.total_usd:.6f}"
    )


async def run(use_telegram: bool) -> None:
    if not os.getenv("OPENAI_API_KEY"):
        print(
            "[ryuu-sensei] ⚠️  OPENAI_API_KEY not set. "
            "Tools won't fire with the fake provider — set the key for the full demo.\n"
        )

    # TodoSensei builds and caches per-user agents internally — no agent= needed
    sensei = TodoSensei()
    sensei.register_channel(CLIAdapter())

    if use_telegram:
        from examples.ryuu_sensei.telegram_adapter import TelegramAdapter

        def _on_verbose(user_id: str, on: bool) -> str:
            sensei.set_verbose("telegram", user_id, on)
            return f"Verbose is now **{'on' if on else 'off'}**."

        def _on_model(user_id: str, model: str) -> str:
            s = sensei.set_model("telegram", user_id, model)
            return f"Model switched to **{s.model}**."

        tg = TelegramAdapter(
            on_clear=lambda user_id: sensei.clear_session("telegram", user_id),
            on_verbose=_on_verbose,
            on_model=_on_model,
            on_settings=lambda user_id: _format_settings(sensei, "telegram", user_id),
            on_status=lambda user_id: _format_status(sensei, "telegram", user_id),
            on_current_model=lambda user_id: sensei.get_settings("telegram", user_id).model,
            allowed_models=ALLOWED_MODELS,
        )
        sensei.register_channel(tg)

    try:
        await sensei.start()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await sensei.stop()


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
