"""Telegram channel adapter — IChannelAdapter impl on aiogram v3 polling.

Setup:
    pip install 'aiogram>=3.0'
    export TELEGRAM_BOT_TOKEN='123456:ABC...'    # from @BotFather

Built-in slash command handlers (NOT forwarded to the LLM):
    /start     welcome banner (uses `welcome_text` if provided)
    /help      usage hints (uses `help_text` if provided)
    /clear     wipes session — calls `on_clear(sender_id, conversation_id)`
    /settings  shows settings — `on_settings(sender_id, conversation_id) -> str`
    /status    shows usage — `on_status(sender_id, conversation_id) -> str`
    /verbose   toggles trace — `on_verbose(sender_id, conv_id, on: bool) -> str`
    /model     interactive switcher with inline keyboard:
                   no-arg: shows current + buttons
                   arg:    `on_model(sender_id, conv_id, name) -> str`
                   tap:    same callback, but via callback_query

All `on_*` hooks are OPTIONAL — adapter degrades gracefully if not provided.

Design choices:
    • Plain-text replies (no parse_mode) — avoids MarkdownV2 escaping bugs
    • Polling mode only — webhook deferred to a later phase
    • Errors in `on_message` turn into a friendly user reply (never propagate)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from ryuu_messaging_core import (
    IChannelAdapter,
    IncomingMessage,
    OnMessageHandler,
    OutgoingMessage,
)

log = logging.getLogger("ryuu_messaging.telegram")


DEFAULT_WELCOME = (
    "Konnichiwa! I am your assistant.\n\n"
    "Commands: /help  /clear  /status"
)

DEFAULT_HELP = (
    "Commands:\n"
    "  /start                  — welcome banner\n"
    "  /help                   — this message\n"
    "  /clear                  — forget our conversation so far\n"
    "  /settings               — show your current settings\n"
    "  /status                 — context size, token usage, cost so far\n"
    "  /verbose on|off         — toggle LLM reasoning trace (💭 🔧 📋)\n"
    "  /model                  — tap a button to switch model\n"
    "  /compact                — compact long history NOW (free up context)\n"
    "  /auto_compact on|off    — toggle automatic compaction\n\n"
    "Or just chat naturally."
)

CLEARED = "Conversation memory cleared. Starting fresh."


@dataclass
class TelegramAdapter(IChannelAdapter):
    """Telegram adapter using aiogram v3 polling. One bot per process."""

    channel_name: str = "telegram"
    bot_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))

    # Slash-command callbacks — all async, all take (sender_id, conversation_id, [extra])
    on_clear: Any = None         # async (sender_id, conv_id) -> None
    on_verbose: Any = None       # async (sender_id, conv_id, on: bool) -> str
    on_model: Any = None         # async (sender_id, conv_id, model: str) -> str
    on_settings: Any = None      # async (sender_id, conv_id) -> str
    on_status: Any = None        # async (sender_id, conv_id) -> str
    on_current_model: Any = None # async (sender_id, conv_id) -> str
    on_compact: Any = None       # async (sender_id, conv_id) -> str  — manual trigger
    on_auto_compact: Any = None  # async (sender_id, conv_id, on: bool|None) -> str  — toggle / status

    # Customizable text + model allowlist for the inline keyboard
    welcome_text: str = DEFAULT_WELCOME
    help_text: str = DEFAULT_HELP
    allowed_models: tuple[str, ...] = ()

    # Sender allowlist — restrict bot to specific Telegram user IDs.
    # Use for single-tenant SuperBot (only owner can DM) or premium-tier gating.
    # None (default) = open to anyone who can find the bot.
    # set() / frozenset(...) = ONLY listed senders get responses; others see a
    # friendly "private bot" message and message never enters the handler.
    allowed_senders: frozenset[str] | None = None
    rejection_message: str = (
        "Sorry, this is a private assistant. "
        "If you think this is wrong, contact the owner."
    )

    _bot: Any = field(default=None, init=False)
    _dp: Any = field(default=None, init=False)
    _chats: dict[str, int] = field(default_factory=dict, init=False)

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

        def _ids(tg_msg: TgMessage) -> tuple[str, str] | None:
            """Extract (sender_id, conversation_id). None if no from_user."""
            if tg_msg.from_user is None:
                return None
            return str(tg_msg.from_user.id), f"telegram:{tg_msg.chat.id}"

        def _model_keyboard(current: str) -> InlineKeyboardMarkup:
            buttons = [
                [InlineKeyboardButton(
                    text=("✓ " if m == current else "  ") + m,
                    callback_data=f"set_model:{m}",
                )]
                for m in self.allowed_models
            ]
            return InlineKeyboardMarkup(inline_keyboard=buttons)

        # ── /start ────────────────────────────────────────────────────
        @self._dp.message(Command("start"))
        async def _cmd_start(tg_msg: TgMessage) -> None:
            self._remember_chat(tg_msg)
            await self._bot.send_message(tg_msg.chat.id, self.welcome_text)

        # ── /help ─────────────────────────────────────────────────────
        @self._dp.message(Command("help"))
        async def _cmd_help(tg_msg: TgMessage) -> None:
            self._remember_chat(tg_msg)
            await self._bot.send_message(tg_msg.chat.id, self.help_text)

        # ── /clear ────────────────────────────────────────────────────
        @self._dp.message(Command("clear"))
        async def _cmd_clear(tg_msg: TgMessage) -> None:
            self._remember_chat(tg_msg)
            ids = _ids(tg_msg)
            if self.on_clear is not None and ids is not None:
                try:
                    await self.on_clear(*ids)
                except Exception as exc:  # noqa: BLE001
                    log.warning("on_clear failed: %s", exc)
            await self._bot.send_message(tg_msg.chat.id, CLEARED)

        # ── /settings ─────────────────────────────────────────────────
        @self._dp.message(Command("settings"))
        async def _cmd_settings(tg_msg: TgMessage) -> None:
            self._remember_chat(tg_msg)
            ids = _ids(tg_msg)
            if self.on_settings is None or ids is None:
                await self._bot.send_message(tg_msg.chat.id, "(settings unavailable)")
                return
            try:
                summary = await self.on_settings(*ids)
            except Exception as exc:  # noqa: BLE001
                log.warning("on_settings failed: %s", exc)
                summary = f"⚠️ {type(exc).__name__}: {exc}"
            await self._bot.send_message(tg_msg.chat.id, summary)

        # ── /status ───────────────────────────────────────────────────
        @self._dp.message(Command("status"))
        async def _cmd_status(tg_msg: TgMessage) -> None:
            self._remember_chat(tg_msg)
            ids = _ids(tg_msg)
            if self.on_status is None or ids is None:
                await self._bot.send_message(tg_msg.chat.id, "(status unavailable)")
                return
            try:
                summary = await self.on_status(*ids)
            except Exception as exc:  # noqa: BLE001
                log.warning("on_status failed: %s", exc)
                summary = f"⚠️ {type(exc).__name__}: {exc}"
            await self._bot.send_message(tg_msg.chat.id, summary)

        # ── /compact — Phase 9.0c manual trigger ─────────────────────
        @self._dp.message(Command("compact"))
        async def _cmd_compact(tg_msg: TgMessage) -> None:
            self._remember_chat(tg_msg)
            ids = _ids(tg_msg)
            if self.on_compact is None or ids is None:
                await self._bot.send_message(tg_msg.chat.id, "(compact unavailable)")
                return
            await self._bot.send_chat_action(tg_msg.chat.id, "typing")
            try:
                reply = await self.on_compact(*ids)
            except Exception as exc:  # noqa: BLE001
                log.warning("on_compact failed: %s", exc)
                reply = f"⚠️ {type(exc).__name__}: {exc}"
            await self._bot.send_message(tg_msg.chat.id, reply)

        # ── /auto_compact — toggle / status ──────────────────────────
        @self._dp.message(Command("auto_compact"))
        async def _cmd_auto_compact(tg_msg: TgMessage) -> None:
            self._remember_chat(tg_msg)
            ids = _ids(tg_msg)
            if ids is None or self.on_auto_compact is None:
                await self._bot.send_message(tg_msg.chat.id, "(auto_compact unavailable)")
                return
            parts = (tg_msg.text or "").strip().split(maxsplit=1)
            arg = parts[1].strip().lower() if len(parts) > 1 else ""

            on: bool | None
            if arg == "on":
                on = True
            elif arg == "off":
                on = False
            elif arg in {"", "status"}:
                on = None   # query current state
            else:
                await self._bot.send_message(
                    tg_msg.chat.id,
                    "Usage: `/auto_compact on|off` to toggle, or `/auto_compact` to see current state.",
                )
                return

            try:
                reply = await self.on_auto_compact(*ids, on)
            except Exception as exc:  # noqa: BLE001
                log.warning("on_auto_compact failed: %s", exc)
                reply = f"⚠️ {type(exc).__name__}: {exc}"
            await self._bot.send_message(tg_msg.chat.id, reply)

        # ── /verbose ──────────────────────────────────────────────────
        @self._dp.message(Command("verbose"))
        async def _cmd_verbose(tg_msg: TgMessage) -> None:
            self._remember_chat(tg_msg)
            ids = _ids(tg_msg)
            if ids is None:
                return
            parts = (tg_msg.text or "").strip().split(maxsplit=1)
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
                reply = await self.on_verbose(*ids, arg == "on")
            except Exception as exc:  # noqa: BLE001
                log.warning("on_verbose failed: %s", exc)
                reply = f"⚠️ {type(exc).__name__}: {exc}"
            await self._bot.send_message(tg_msg.chat.id, reply)

        # ── /model — interactive switcher ─────────────────────────────
        @self._dp.message(Command("model"))
        async def _cmd_model(tg_msg: TgMessage) -> None:
            self._remember_chat(tg_msg)
            ids = _ids(tg_msg)
            if ids is None:
                return
            sender_id, conv_id = ids

            # Explicit arg form: /model <name>
            parts = (tg_msg.text or "").strip().split(maxsplit=1)
            if len(parts) > 1 and parts[1].strip():
                if self.on_model is None:
                    await self._bot.send_message(tg_msg.chat.id, "(model switch unavailable)")
                    return
                try:
                    reply = await self.on_model(sender_id, conv_id, parts[1].strip())
                except Exception as exc:  # noqa: BLE001
                    log.warning("on_model failed: %s", exc)
                    reply = f"⚠️ {type(exc).__name__}: {exc}"
                await self._bot.send_message(tg_msg.chat.id, reply)
                return

            # No arg → show current + inline keyboard
            current = ""
            if self.on_current_model is not None:
                try:
                    current = await self.on_current_model(sender_id, conv_id)
                except Exception as exc:  # noqa: BLE001
                    log.warning("on_current_model failed: %s", exc)
            header = (
                f"Current model: **{current}**\n\nTap to switch:"
                if current else "Tap to switch model:"
            )
            await self._bot.send_message(
                tg_msg.chat.id, header, reply_markup=_model_keyboard(current)
            )

        @self._dp.callback_query(F.data.startswith("set_model:"))
        async def _cb_model(cq: CallbackQuery) -> None:
            sender_id = str(cq.from_user.id)
            # Recover conversation_id from the original message's chat
            conv_id = (
                f"telegram:{cq.message.chat.id}"
                if cq.message is not None
                else f"telegram:{cq.from_user.id}"
            )
            model = (cq.data or "").split(":", 1)[1] if cq.data else ""
            if self.on_model is None or not model:
                await cq.answer("(unavailable)")
                return
            try:
                await self.on_model(sender_id, conv_id, model)
                ok, body = True, f"✅ Switched to **{model}**"
            except Exception as exc:  # noqa: BLE001
                log.warning("on_model failed: %s", exc)
                ok, body = False, f"⚠️ {type(exc).__name__}: {exc}"
            await cq.answer("Switched" if ok else "Failed")
            if cq.message is not None:
                try:
                    await cq.message.edit_text(
                        body, reply_markup=_model_keyboard(model if ok else "")
                    )
                except Exception:  # noqa: BLE001 — Telegram dislikes same-text edits
                    pass

        # ── Free-form message ─────────────────────────────────────────
        @self._dp.message()
        async def _handler(tg_msg: TgMessage) -> None:
            if not tg_msg.text:
                return  # ignore stickers/photos/etc.

            # Single-tenant gate: reject non-allowlisted senders early.
            # Applies to free-form messages only — slash commands let users
            # see /help even if they can't actually use the bot.
            sender = str(tg_msg.from_user.id) if tg_msg.from_user else ""
            if self.allowed_senders is not None and sender not in self.allowed_senders:
                log.info("Rejecting message from non-allowlisted sender %s", sender)
                await self._bot.send_message(tg_msg.chat.id, self.rejection_message)
                return

            self._remember_chat(tg_msg)
            incoming = IncomingMessage(
                channel=self.channel_name,
                sender_id=sender or "unknown",
                conversation_id=f"telegram:{tg_msg.chat.id}",
                text=tg_msg.text,
                metadata={"chat_type": tg_msg.chat.type},
            )
            await self._bot.send_chat_action(tg_msg.chat.id, "typing")
            try:
                reply = await on_message(incoming)
            except Exception as exc:  # noqa: BLE001
                log.exception("on_message failed")
                reply = OutgoingMessage(
                    conversation_id=incoming.conversation_id,
                    text=f"⚠️ Something went wrong: {type(exc).__name__}. "
                         "Try /clear and ask again.",
                )
            await self.send(reply)

        log.info("Telegram adapter started; polling for updates…")
        print("[ryuu-messaging] Telegram adapter started — polling for messages.")
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
            try:
                chat_id = int(msg.conversation_id.split(":", 1)[1])
            except (IndexError, ValueError) as e:
                raise ValueError(
                    f"Cannot resolve chat_id from conversation_id={msg.conversation_id!r}"
                ) from e
        if not msg.text:
            return  # suppress empty replies (e.g. STOP already sent its own summary)
        await self._bot.send_message(chat_id, msg.text)

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
        conv_id = f"telegram:{tg_msg.chat.id}"
        self._chats[conv_id] = tg_msg.chat.id
