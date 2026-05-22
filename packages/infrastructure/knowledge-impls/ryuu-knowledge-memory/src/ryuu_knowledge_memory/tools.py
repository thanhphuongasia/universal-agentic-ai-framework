"""MemoryToolset — pre-built memory tools for any IChannelHandler.

Industry pattern: framework ships TOOLS (utilities), product owns POLICY
(when/what to write, where to inject recall in prompt). MemoryToolset
encapsulates the tool functions + scope binding so consumers don't rewrite
~120 LOC of contextvar plumbing per product.

Usage:
    from ryuu_knowledge_memory.tools import MemoryToolset

    toolset = MemoryToolset(backbone=my_backbone)
    agent = Agent(tools=toolset.tools, ...)

    # Bind scope per turn — LLM tool calls inside this block read/write
    # to `scope_key` automatically.
    async with toolset.bind(scope_key=session.scope_key):
        result = await agent.run(message=prompt)

Default tools (always-on, all safe):
    remember(fact)     — INSERT — adds observation
    recall(query)      — SELECT — keyword-overlap search
    list_memories()    — SELECT — recent N, no filter

Opt-in tool (destructive — requires explicit consent):
    forget(query)      — DELETE — pass include_forget=True

Why `forget` is opt-in:
  Destructive ops should require explicit grant (Claude SDK / AWS Bedrock
  default-safe pattern). LLM misinterpretation ("forget the Tokyo plan,
  Osaka instead" intended as UPDATE) or social-engineering ("forget
  everything you know about me") could wipe data otherwise.
"""

from __future__ import annotations

import contextvars
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Callable

from ryuu_knowledge_base.backbone import IKnowledgeBackbone


# Three always-safe tools. `forget` excluded — opt-in via include_forget=True.
_DEFAULT_TOOL_NAMES: tuple[str, ...] = ("remember", "recall", "list_memories")


@dataclass
class MemoryToolset:
    """Pre-built memory tools bound to an IKnowledgeBackbone.

    Each instance owns its own contextvar so multiple toolsets in the same
    process don't collide.
    """
    backbone: IKnowledgeBackbone
    include_forget: bool = False
    tool_names: tuple[str, ...] | None = None
    """Explicit tool selection. Overrides default + include_forget.
    Use only when you want a non-default subset (e.g. recall-only)."""

    top_k: int = 5
    list_limit: int = 10

    _scope_var: contextvars.ContextVar = field(default=None, init=False)  # type: ignore[assignment]
    _tools_built: list[Callable] = field(default=None, init=False)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        # Per-instance contextvar — id() in name keeps multiple toolsets isolated
        self._scope_var = contextvars.ContextVar(
            f"ryuu_memory_toolset_scope_{id(self)}", default=None
        )
        self._tools_built = self._build_tools()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    @property
    def tools(self) -> list[Callable]:
        """Tool functions ready for `Agent(tools=...)`. Already closure-bound
        to this toolset's backbone + scope contextvar."""
        return self._tools_built

    @asynccontextmanager
    async def bind(self, scope_key: str):
        """Bind scope for tool calls inside the `async with` block.

        Tools inside this block read/write to `scope_key`. Restored on exit.
        Nesting works (inner overrides outer).
        """
        token = self._scope_var.set(scope_key)
        try:
            yield
        finally:
            self._scope_var.reset(token)

    # ------------------------------------------------------------------ #
    # Internal — build tool functions as closures
    # ------------------------------------------------------------------ #
    def _build_tools(self) -> list[Callable]:
        all_tools = self._all_tool_impls()

        if self.tool_names is not None:
            # Explicit selection — honor as-is
            selected = self.tool_names
        else:
            selected = _DEFAULT_TOOL_NAMES
            if self.include_forget and "forget" not in selected:
                selected = selected + ("forget",)

        out: list[Callable] = []
        for name in selected:
            if name in all_tools:
                out.append(all_tools[name])
        return out

    def _all_tool_impls(self) -> dict[str, Callable]:
        bb = self.backbone
        scope_var = self._scope_var
        top_k = self.top_k
        list_limit = self.list_limit

        async def remember(fact: str) -> str:
            """Save a fact about the user or our conversation for future sessions.

            Call this when the user shares something worth remembering across
            sessions: their name, preferences, goals, important decisions,
            recurring topics.

            Args:
                fact: A short statement worth remembering, e.g. "User's name
                      is Phuong" or "Prefers gpt-4o for code review tasks".

            Returns:
                Confirmation that the fact was stored.
            """
            scope = scope_var.get()
            if scope is None:
                return "(memory not bound to a scope in this context)"
            await bb.write(
                observation=fact.strip(),
                scope_key=scope,
                metadata={"source": "explicit"},
            )
            return f"Remembered: {fact.strip()[:120]}"

        async def recall(query: str) -> str:
            """Search past memory for observations matching a query.

            Use when the user asks about prior conversations or facts you may
            have remembered before. Returns the top-K most relevant entries.

            Args:
                query: Natural-language description of what to search for.

            Returns:
                Bullet-list of matching memories, or a "no memories" message.
            """
            scope = scope_var.get()
            if scope is None:
                return "(memory not bound)"
            result = await bb.query(query, scope_key=scope, top_k=top_k)
            if not result.results:
                return f"I don't have any memories matching {query!r}."
            lines = [f"Found {len(result.results)} memory entries about {query!r}:"]
            for content in result.results:
                lines.append(f"  • {content}")
            return "\n".join(lines)

        async def list_memories() -> str:
            """List the most recent memory entries (no query filter).

            Useful when the user asks "what do you know about me?".

            Returns:
                Bullet-list of the latest N memory entries.
            """
            scope = scope_var.get()
            if scope is None:
                return "(memory not bound)"
            result = await bb.query("", scope_key=scope, top_k=list_limit)
            if not result.results:
                return "I have no memories about you yet. Tell me about yourself!"
            return "Recent memories:\n" + "\n".join(f"  • {r}" for r in result.results)

        async def forget(query: str) -> str:
            """DESTRUCTIVE — delete memory entries matching the query.

            CURRENTLY NOT IMPLEMENTED for safety. Would require:
              1. IKnowledgeBackbone.delete(item_id) — not yet in Protocol
              2. HITL confirmation gate (LLM asks user before destroying data)

            For now: returns a safe refusal pointing users at manual deletion.
            """
            return (
                "Selective forget is not implemented yet. To wipe memory "
                "completely, delete the JSONL files in your memory directory "
                "(e.g. ~/.ryuu/memory/episodic/<scope>.jsonl)."
            )

        return {
            "remember": remember,
            "recall": recall,
            "list_memories": list_memories,
            "forget": forget,
        }


__all__ = ["MemoryToolset"]
