"""Session scoping — load-bearing structural decision.

Every memory write/read MUST be keyed by `SessionKey = f"{channel}:{user_id}"`
to prevent cross-user / cross-channel leakage.

For MVP this is an in-memory dict. In real deployment, swap SessionStore for
a MemoryBackbone (vector + BM25 hybrid search, see Phase 9.3 in roadmap).
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Iterable

# Type alias for clarity. SessionKey is just a string of the form "channel:user_id"
SessionKey = str


def make_session_key(channel: str, user_id: str) -> SessionKey:
    """Canonical key constructor — ALWAYS go through this. Never f-string yourself."""
    return f"{channel}:{user_id}"


@dataclass
class Turn:
    role: str       # "user" | "assistant"
    text: str


@dataclass
class SessionStore:
    """In-memory short-term conversation buffer per session.

    Swap for `MemoryBackbone` + `ContextAssembler` (from ryuu framework) when
    integrating real long-term memory. The interface (append / recent) is
    intentionally compatible.
    """
    max_turns: int = 20
    _buffers: dict[SessionKey, deque[Turn]] = field(default_factory=lambda: defaultdict(deque))

    def append(self, key: SessionKey, role: str, text: str) -> None:
        buf = self._buffers[key]
        buf.append(Turn(role=role, text=text))
        while len(buf) > self.max_turns:
            buf.popleft()

    def recent(self, key: SessionKey, n: int | None = None) -> list[Turn]:
        buf = self._buffers[key]
        if n is None:
            return list(buf)
        return list(buf)[-n:]

    def clear(self, key: SessionKey) -> None:
        self._buffers.pop(key, None)

    def all_keys(self) -> Iterable[SessionKey]:
        return list(self._buffers.keys())
