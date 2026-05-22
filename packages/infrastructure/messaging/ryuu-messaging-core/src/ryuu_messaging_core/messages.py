"""Canonical message types — channel-agnostic.

Every channel adapter (Telegram, Slack, Discord, CLI) translates its native
payload into these types at the boundary. Core code never sees a raw
Telegram update or Slack event.

Two identity fields, intentionally separate even though Telegram 1-1 chat
collapses them:
  • conversation_id — *where* the message lives (chat / room / thread)
  • sender_id       — *who* spoke (the human actor)

Telegram DM: conversation_id == sender_id == user_id (effectively).
Slack channel: conversation_id = "C0XYZ"; sender_id = "U0ABC" — different.
Refactoring this split LATER means touching every call site → cheaper to
keep separate from day one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Attachment:
    """File/image/audio attached to a message."""
    kind: str           # "image" | "audio" | "file" | "video"
    url: str | None = None
    data: bytes | None = None
    mime_type: str | None = None
    filename: str | None = None


@dataclass(frozen=True)
class Action:
    """Interactive UI element (button, quick-reply). Adapter maps to native form."""
    label: str
    value: str
    style: str = "default"   # "default" | "primary" | "danger"


@dataclass
class IncomingMessage:
    """A user message normalized from any channel."""
    channel: str                # "telegram" | "slack" | "discord" | "cli"
    sender_id: str              # who spoke — platform user id
    conversation_id: str        # where it was said — chat / room / thread id
    text: str
    attachments: list[Attachment] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    # ↑ metadata is the "open bag" for platform-specific extras (Telegram
    # reply_to_message_id, Slack thread_ts, Discord guild_id…). Promote to
    # a typed field ONLY when ≥3 channels need it (rule of three).


@dataclass
class OutgoingMessage:
    """Assistant's reply destined for a channel."""
    conversation_id: str
    text: str
    formatting: str = "markdown"   # "markdown" | "html" | "plain"
    actions: list[Action] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
