# ryuu-knowledge-memory

Memory backbone + quality layer + conversational glue for RYUU agents.

The package gives you the **mechanism** (storage, retrieval, consolidation,
turn buffering). Your app keeps the **policy** (what to store, voice/wording,
when to consolidate). That split is deliberate — it's why one backbone serves
a tutor, a todo bot, and a support bot without forking.

## Layers

| Component | Role |
|-----------|------|
| `WorkingMemoryStore` | recent buffer, FIFO (e.g. max 50), persisted |
| `EpisodicMemoryStore` | longer-term observations (keyword-overlap scoring + lifecycle) |
| `SemanticMemoryStore` | consolidated long-term facts (written by `DreamingConsolidator`) |
| `MemoryBackbone` | composes the stores into one Working→Episodic backbone |
| `MemoryToolset` | pre-built `remember` / `recall` / `list_memories` tools |

**Quality layer (optional, pass to `MemoryBackbone`):**
`ExtractionFilter` (LLM signal/noise filter), `DreamingConsolidator`
(episodic→semantic, post-session), `EvictionJob` (importance-weighted decay).

## ConversationMemory — short-term continuity

**Problem it solves:** nearly every chat/agent product needs the same two
operations, and used to re-implement the glue each time:

1. after each turn, drop the `(user question, assistant reply)` pair into a
   rolling buffer so context survives a restart / new session;
2. before each turn, pull the last few exchanges back as a text block to
   prepend to the prompt.

The storage already lives in `WorkingMemoryStore`. What every app copied was
the thin glue: prefix wording, truncation lengths, how many turns to recall,
how to render the block. `ConversationMemory` owns that glue with the
wording/limits **injected** via `TurnFormat`, so each app keeps its voice while
sharing the mechanism.

```python
from ryuu_knowledge_memory import ConversationMemory, TurnFormat

conv = ConversationMemory(
    working_store,
    fmt=TurnFormat(
        question_prefix="Học viên hỏi: ",   # your domain voice
        answer_prefix="Bot trả lời: ",
        max_question=280,                    # truncate — buffer is an anchor, not a transcript
        max_answer=360,
        recent_header="💬 Recent exchanges:",
    ),
    top_k=6,                                 # ~3 exchanges (Q+A each)
)

# after a turn
await conv.record(scope_key, user_text, assistant_reply)

# before the next turn — prepend to the prompt
block = await conv.recent_block(scope_key)
```

**What stays in your app (intentionally NOT in this helper):**

- consolidation policy (when working→episodic distillation runs),
- semantic / domain retrieval (e.g. a concept graph),
- the MCP toolset.

Those are product-specific. `ConversationMemory` is only the conversational-turn
buffer. It **never raises** — `record` degrades to a no-op and `recent_block`
to `""` on failure, so a memory hiccup can't break a chat turn.

**Scope:** everything is keyed by `scope_key` (convention `"<bot>:<user>"`).
Different users → different buffers, never cross-read.

> Note on scope: this helper handles the *memory* side. Mapping a channel +
> sender → `scope_key` is a separate concern owned by
> `ryuu-messaging-core`'s `ConversationManager`.
