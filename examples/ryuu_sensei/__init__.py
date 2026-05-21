"""Ryuu Sensei — multi-channel AI assistant sample.

See README.md for architecture. This package demonstrates the channel-agnostic
core (RyuuSensei + IChannelAdapter) with a working CLI adapter and a
Telegram adapter stub.

Layers (matches OpenClaw 4-layer architecture):
  1. Channel Layer       → channel.py + cli_adapter.py + telegram_adapter.py
  2. Gateway Control     → sensei.py (session scoping, message routing)
  3. Agent Runtime       → sensei.py (LLM + ReAct loop; uses ryuu framework)
  4. Memory & Tools      → session.py (in-memory; swap to MemoryBackbone for real use)
"""

from examples.ryuu_sensei.messages import (
    Action,
    Attachment,
    IncomingMessage,
    OutgoingMessage,
)
from examples.ryuu_sensei.channel import IChannelAdapter
from examples.ryuu_sensei.session import SessionKey, SessionStore, Turn
from examples.ryuu_sensei.sensei import DEFAULT_INSTRUCTIONS, RyuuSensei

__all__ = [
    "Action",
    "Attachment",
    "DEFAULT_INSTRUCTIONS",
    "IChannelAdapter",
    "IncomingMessage",
    "OutgoingMessage",
    "RyuuSensei",
    "SessionKey",
    "SessionStore",
    "Turn",
]
