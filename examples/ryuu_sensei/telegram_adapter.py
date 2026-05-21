"""Telegram channel adapter (Phase 9.2).

Implements IChannelAdapter for Telegram via aiogram v3 polling.

Setup:
    pip install 'aiogram>=3.0'
    export TELEGRAM_BOT_TOKEN='123456:ABC...'    # from @BotFather
    python -m examples.ryuu_sensei.main --telegram

Commands handled at the adapter (NOT forwarded to the LLM):
    /start    welcome banner
    /help     usage hints
    /clear    wipe this user's short-term conversation memory

Design choices:
    • Plain-text replies (no parse_mode) — avoids the MarkdownV2 escaping
      minefield (`_`, `*`, `[`, `]`, `(`, `)`, `~`, etc. all need escaping
      in MarkdownV2; a single un-escaped char breaks the whole message).
      The LLM's reply usually contains punctuation that would trip MarkdownV2.
    • Polling mode only — webhook deployment is Phase 9.4 (cron + push).
    • Errors from the LLM / tool layer become a friendly user message
      instead of leaking tracebacks into the chat.

Deferred to a later phase (not in this file):
    • Human-in-the-loop approval flow for risky tools
    • Inline keyboards for `OutgoingMessage.actions`
    • File / image attachment handling
    • Webhook mode + signature verification
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from examples.ryuu_sensei.channel import IChannelAdapter, OnMessageHandler
from examples.ryuu_sensei.messages import IncomingMessage, OutgoingMessage

log = logging.getLogger("ryuu_sensei.telegram")


WELCOME = (
    "Konnichiwa! I am Ryuu Sensei (流先生).\n\n"
    "I can help you manage todos. Try:\n"
    "  • add a todo: buy milk\n"
    "  • show my list\n"
    "  • mark #1 done\n\n"
    "Commands: /help  /clear"
)

HELP = (
    "Commands:\n"
    "  /start            — welcome banner\n"
    "  /help             — this message\n"
    "  /clear            — forget our conversation so far\n"
    "  /settings         — show your current settings\n"
    "  /status           — context size, token usage, cost so far\n"
    "  /verbose on|off   — toggle LLM reasoning trace (💭 🔧 📋)\n"
    "  /model            — tap a button to switch model\n\n"
    "Or just chat naturally. I'll call tools when needed."
)

CLEARED = "Conversation memory cleared. Starting fresh."


@dataclass
class TelegramAdapter(IChannelAdapter):
    """Telegram adapter using aiogram v3 polling. One bot per process."""

    channel_name: str = "telegram"
    bot_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    # Hooks the sensei provides so commands can mutate per-user state.
    # All optional — adapter degrades gracefully if a hook is None.
    on_clear: Any = None         # Callable[[user_id: str], None]
    on_verbose: Any = None       # Callable[[user_id: str, on: bool], str]
    on_model: Any = None         # Callable[[user_id: str, model: str], str]
    on_settings: Any = None      # Callable[[user_id: str], str]
    on_status: Any = None        # Callable[[user_id: str], str]
    on_current_model: Any = None # Callable[[user_id: str], str]
    allowed_models: tuple[str, ...] = ()

    _bot: Any = field(default=None, init=False)
    _dp: Any = field(default=None, init=False)
    _chats: dict[str, int] = field(default_factory=dict, init=False)  # conv_id → tg chat_id

    def __post_init__(self) -> None:
        if not self.bot_token:
            raise RuntimeError(
                "TELEGRAM_BOT_TOKEN not set. Get one from @BotFather and "
                "`export TELEGRAM_BOT_TOKEN=...`. Never commit it."
            )

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    async def start(self, on_message: OnMessageHandler) -> None:
        try:
            from aiogram import Bot, Dispatcher, F
            from aiogram.filters import Command
            from aiogram.types import (
                CallbackQuery,
                InlineKeyboardButton,
                InlineKeyboardMarkup,
                Message as TgMessage,
            )
        except ImportError as e:
            raise RuntimeError(
                "aiogram is not installed. Run: pip install 'aiogram>=3.0'"
            ) from e

        self._bot = Bot(token=self.bot_token)
        self._dp = Dispatcher()

        # ── /start ────────────────────────────────────────────────────
        @self._dp.message(Command("start"))
        async def _cmd_start(tg_msg: TgMessage) -> None:
            self._remember_chat(tg_msg)
            await self._bot.send_message(tg_msg.chat.id, WELCOME)

        # ── /help ─────────────────────────────────────────────────────
        @self._dp.message(Command("help"))
        async def _cmd_help(tg_msg: TgMessage) -> None:
            self._remember_chat(tg_msg)
            await self._bot.send_message(tg_msg.chat.id, HELP)

        # ── /clear ────────────────────────────────────────────────────
        @self._dp.message(Command("clear"))
        async def _cmd_clear(tg_msg: TgMessage) -> None:
            self._remember_chat(tg_msg)
            if self.on_clear is not None and tg_msg.from_user is not None:
                try:
                    self.on_clear(str(tg_msg.from_user.id))
                except Exception as exc:  # noqa: BLE001 — never propagate
                    log.warning("on_clear failed: %s", exc)
            await self._bot.send_message(tg_msg.chat.id, CLEARED)

        # ── /settings ─────────────────────────────────────────────────
        @self._dp.message(Command("settings"))
        async def _cmd_settings(tg_msg: TgMessage) -> None:
            self._remember_chat(tg_msg)
            if self.on_settings is None or tg_msg.from_user is None:
                await self._bot.send_message(tg_msg.chat.id, "(settings unavailable)")
                return
            try:
                summary = self.on_settings(str(tg_msg.from_user.id))
            except Exception as exc:  # noqa: BLE001
                log.warning("on_settings failed: %s", exc)
                summary = f"⚠️ {type(exc).__name__}: {exc}"
            await self._bot.send_message(tg_msg.chat.id, summary)

        # ── /verbose ──────────────────────────────────────────────────
        @self._dp.message(Command("verbose"))
        async def _cmd_verbose(tg_msg: TgMessage) -> None:
            self._remember_chat(tg_msg)
            if tg_msg.from_user is None:
                return
            text = (tg_msg.text or "").strip()
            parts = text.split(maxsplit=1)
            arg = parts[1].strip().lower() if len(parts) > 1 else ""

            if arg not in {"on", "off"}:
                await self._bot.send_message(
                    tg_msg.chat.id,
                    "Usage: `/verbose on` or `/verbose off`\n"
                    "When on, I'll show my reasoning steps (💭 🔧 📋).",
                )
                return

            if self.on_verbose is None:
                await self._bot.send_message(tg_msg.chat.id, "(verbose toggle unavailable)")
                return

            try:
                reply = self.on_verbose(str(tg_msg.from_user.id), arg == "on")
            except Exception as exc:  # noqa: BLE001
                log.warning("on_verbose failed: %s", exc)
                reply = f"⚠️ {type(exc).__name__}: {exc}"
            await self._bot.send_message(tg_msg.chat.id, reply)

        # ── /model — interactive switcher with inline keyboard ────────
        def _model_keyboard(current: str) -> InlineKeyboardMarkup:
            buttons = [
                [InlineKeyboardButton(
                    text=("✓ " if m == current else "  ") + m,
                    callback_data=f"set_model:{m}",
                )]
                for m in self.allowed_models
            ]
            return InlineKeyboardMarkup(inline_keyboard=buttons)

        @self._dp.message(Command("model"))
        async def _cmd_model(tg_msg: TgMessage) -> None:
            self._remember_chat(tg_msg)
            if tg_msg.from_user is None:
                return
            user_id = str(tg_msg.from_user.id)

            # If user passed an explicit name, treat it like the old behavior
            parts = (tg_msg.text or "").strip().split(maxsplit=1)
            if len(parts) > 1 and parts[1].strip():
                arg = parts[1].strip()
                if self.on_model is None:
                    await self._bot.send_message(tg_msg.chat.id, "(model switch unavailable)")
                    return
                try:
                    reply = self.on_model(user_id, arg)
                except Exception as exc:  # noqa: BLE001
                    log.warning("on_model failed: %s", exc)
                    reply = f"⚠️ {type(exc).__name__}: {exc}"
                await self._bot.send_message(tg_msg.chat.id, reply)
                return

            # No arg → show current + inline keyboard
            current = ""
            if self.on_current_model is not None:
                try:
                    current = self.on_current_model(user_id)
                except Exception as exc:  # noqa: BLE001
                    log.warning("on_current_model failed: %s", exc)
            header = (
                f"Current model: **{current}**\n\nTap to switch:"
                if current else "Tap to switch model:"
            )
            await self._bot.send_message(
                tg_msg.chat.id,
                header,
                reply_markup=_model_keyboard(current),
            )

        @self._dp.callback_query(F.data.startswith("set_model:"))
        async def _cb_model(cq: CallbackQuery) -> None:
            user_id = str(cq.from_user.id)
            model = (cq.data or "").split(":", 1)[1] if cq.data else ""
            if self.on_model is None or not model:
                await cq.answer("(unavailable)")
                return
            try:
                self.on_model(user_id, model)
                ok = True
                msg_text = f"✅ Switched to **{model}**"
            except Exception as exc:  # noqa: BLE001
                log.warning("on_model failed: %s", exc)
                ok = False
                msg_text = f"⚠️ {type(exc).__name__}: {exc}"
            # Acknowledge the tap (removes "loading" spinner on the button)
            await cq.answer("Switched" if ok else "Failed")
            # Edit the original message to reflect new state
            if cq.message is not None:
                try:
                    await cq.message.edit_text(
                        msg_text,
                        reply_markup=_model_keyboard(model if ok else ""),
                    )
                except Exception:  # noqa: BLE001 — Telegram dislikes "same text" edits
                    pass

        # ── /status ───────────────────────────────────────────────────
        @self._dp.message(Command("status"))
        async def _cmd_status(tg_msg: TgMessage) -> None:
            self._remember_chat(tg_msg)
            if self.on_status is None or tg_msg.from_user is None:
                await self._bot.send_message(tg_msg.chat.id, "(status unavailable)")
                return
            try:
                summary = self.on_status(str(tg_msg.from_user.id))
            except Exception as exc:  # noqa: BLE001
                log.warning("on_status failed: %s", exc)
                summary = f"⚠️ {type(exc).__name__}: {exc}"
            await self._bot.send_message(tg_msg.chat.id, summary)

        # ── Free-form message ─────────────────────────────────────────
        @self._dp.message()
        async def _handler(tg_msg: TgMessage) -> None:
            if not tg_msg.text:
                # Ignore stickers / photos / etc. for now
                return
            self._remember_chat(tg_msg)
            incoming = IncomingMessage(
                channel=self.channel_name,
                user_id=str(tg_msg.from_user.id) if tg_msg.from_user else "unknown",
                conversation_id=f"telegram:{tg_msg.chat.id}",
                text=tg_msg.text,
                metadata={"chat_type": tg_msg.chat.type},
            )
            await self._bot.send_chat_action(tg_msg.chat.id, "typing")
            try:
                reply = await on_message(incoming)
            except Exception as exc:  # noqa: BLE001 — friendly error to user
                log.exception("on_message failed")
                reply = OutgoingMessage(
                    conversation_id=incoming.conversation_id,
                    text=f"⚠️ Something went wrong: {type(exc).__name__}. Try /clear and ask again.",
                )
            await self.send(reply)

        log.info("Telegram adapter started; polling for updates…")
        print("[ryuu-sensei] Telegram adapter started — polling for messages.")
        await self._dp.start_polling(self._bot)

    async def stop(self) -> None:
        if self._dp is not None:
            await self._dp.stop_polling()
        if self._bot is not None:
            await self._bot.session.close()

    # ------------------------------------------------------------------ #
    # Outbound
    # ------------------------------------------------------------------ #
    async def send(self, msg: OutgoingMessage) -> None:
        if self._bot is None:
            raise RuntimeError("Adapter not started")
        chat_id = self._chats.get(msg.conversation_id)
        if chat_id is None:
            # Recover from "telegram:<chat_id>" pattern (proactive push case)
            try:
                chat_id = int(msg.conversation_id.split(":", 1)[1])
            except (IndexError, ValueError) as e:
                raise ValueError(
                    f"Cannot resolve chat_id from conversation_id={msg.conversation_id!r}"
                ) from e
        # Plain text — avoid Markdown escaping bugs. Telegram still renders
        # links and basic punctuation fine without parse_mode.
        await self._bot.send_message(chat_id, msg.text or "(empty)")

    async def send_typing(self, conversation_id: str) -> None:
        if self._bot is None:
            return
        chat_id = self._chats.get(conversation_id)
        if chat_id is not None:
            await self._bot.send_chat_action(chat_id, "typing")

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #
    def _remember_chat(self, tg_msg: Any) -> None:
        """Cache the tg chat_id keyed by canonical conversation_id."""
        conv_id = f"telegram:{tg_msg.chat.id}"
        self._chats[conv_id] = tg_msg.chat.id
