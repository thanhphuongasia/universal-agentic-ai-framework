"""Canonical message types — channel-agnostic.

Every channel adapter (Telegram, Slack, Discord, CLI) translates its native
payload into these types at the boundary. The Sensei core never sees a raw
Telegram update or Slack event.
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
    """Interactive UI element (button, quick-reply).

    Each channel adapter maps Action -> its native UI primitive:
      Telegram → InlineKeyboardButton
      Slack    → Block Kit button
      Discord  → ButtonComponent
      CLI      → printed [n] option
    """
    label: str
    value: str          # payload sent back when user picks this action
    style: str = "default"  # "default" | "primary" | "danger"


@dataclass
class IncomingMessage:
    """A user message normalized from any channel."""
    channel: str                # "telegram" | "slack" | "discord" | "cli"
    user_id: str                # platform-native user id (Telegram user_id, Slack U-id, ...)
    conversation_id: str        # f"{channel}:{chat_id}" — unique per chat/dm
    text: str
    attachments: list[Attachment] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class OutgoingMessage:
    """Assistant's reply destined for a channel."""
    conversation_id: str
    text: str
    formatting: str = "markdown"   # "markdown" | "html" | "plain"
    actions: list[Action] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
