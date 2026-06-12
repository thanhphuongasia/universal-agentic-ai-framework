"""ConversationMemory — generic short-term conversational continuity over a
WorkingMemoryStore.

WHY: nearly every chat/agent product needs the same two operations —
  1. after each turn, drop the (user question, assistant reply) pair into a
     rolling buffer so context survives a process restart / new session;
  2. before each turn, pull the last few exchanges back as a text block to
     prepend to the prompt.

The STORAGE (FIFO buffer, persistence, scope isolation) already lives in
WorkingMemoryStore. What every app re-implemented was the thin glue: the
prefix wording, truncation lengths, how many turns to recall, how to render
the block. This class captures that glue with the wording/limits INJECTED so
each app keeps its own voice while sharing the mechanism.

What stays in the app (intentionally NOT here): consolidation policy
(working→episodic distillation), semantic / domain retrieval, and the MCP
toolset. Those are genuinely product-specific. This helper is only the
conversational-turn buffer.

Example:
    conv = ConversationMemory(working_store, fmt=TurnFormat(
        question_prefix="Học viên hỏi: ", answer_prefix="Bot trả lời: "))
    await conv.record(scope_key, user_text, answer)      # store both sides
    block = await conv.recent_block(scope_key)            # prepend to next prompt
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TurnFormat:
    """App-specific wording + limits for how a turn is stored and rendered.

    Defaults are neutral English; apps override to match their domain voice.
    Truncation keeps the buffer an ANCHOR, not a transcript — the live session
    client already holds the full, untruncated history."""
    question_prefix: str = "User asked: "
    answer_prefix: str = "Assistant replied: "
    max_question: int = 280          # cắt câu hỏi (vd user paste cả file code)
    max_answer: int = 360            # đáp án dài hơn hỏi 1 chút; vẫn cắt cho gọn
    recent_header: str = "Recent exchanges:"
    bullet: str = "- "


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


class ConversationMemory:
    """Wraps a WorkingMemoryStore to record turns and recall recent exchanges.

    `store` only needs `.store(content, scope_key, metadata)` and
    `.retrieve(query, scope_key, top_k)` → entries exposing `.content`, which is
    exactly the WorkingMemoryStore contract. No tie to a concrete backend.

    Never raises: memory glue must never break a chat turn — failures degrade to
    a no-op (record) or empty string (recall)."""

    def __init__(self, store, *, fmt: TurnFormat | None = None, top_k: int = 6) -> None:
        self._store = store
        self._fmt = fmt or TurnFormat()
        self._top_k = top_k

    async def record(self, scope_key: str, question: str, answer: str = "") -> bool:
        """Store the turn (question, then answer if present) into the buffer.

        Returns True if at least the question was written — caller can hang
        side-effects (e.g. consolidation counter) off that without re-checking."""
        q = _clip(question, self._fmt.max_question)
        if not q:
            return False
        a = _clip(answer, self._fmt.max_answer)
        try:
            await self._store.store(
                f"{self._fmt.question_prefix}{q}", scope_key, {"source": "auto_turn"}
            )
            if a:
                await self._store.store(
                    f"{self._fmt.answer_prefix}{a}", scope_key, {"source": "auto_turn"}
                )
            return True
        except Exception:  # noqa: BLE001 — memory must never block chat
            return False

    async def recent_block(self, scope_key: str) -> str:
        """Render the last `top_k` buffer entries as a prompt-ready block.
        Empty string if nothing stored or retrieval fails."""
        try:
            recent = await self._store.retrieve("", scope_key, top_k=self._top_k)
        except Exception:  # noqa: BLE001
            return ""
        texts = [e.content for e in recent if getattr(e, "content", "")]
        if not texts:
            return ""
        body = "\n".join(f"{self._fmt.bullet}{t}" for t in texts)
        return f"{self._fmt.recent_header}\n{body}\n\n"
