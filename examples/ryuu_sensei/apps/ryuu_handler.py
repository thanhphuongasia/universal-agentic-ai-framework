"""RyuuHandler — Phase 9.0a SuperBot reference impl.

Single-tenant generalist assistant. Differs from TodoHandler in:

  • Single-tenant: composed with SingleTenantResolver("owner"), so EVERY
    sender (even from different channels) writes/reads the same scope.
    Use with TelegramAdapter(allowed_senders={OWNER_ID}) to gate access.
  • Long-term memory: MemoryBackbone backed by JsonlCollectionStore. Memories
    persist across `/clear` and process restart. Editing
    ~/.ryuu/memory/episodic/owner.jsonl is a valid (and safe) operation.
  • Generalist tools: `remember(fact)`, `recall(query)`, `list_memories()` —
    LLM decides when to call them. Optional add: web-search, filesystem, MCP.
  • Memory-assembled context: every turn loads top-K relevant past
    observations and injects them into the prompt. The LLM gets "what we
    know about you" without you re-typing it.

Does NOT own (Phase 9.x follow-up roadmap):
  • LLM-based context compaction (compactor wiring placeholder below)
  • MCP client manager (cắm Todo Pro / Flash Pro)
  • Query expansion / decomposition (cognitive primitives ready to wire)
  • Approval gate (HITL) for risky tools
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ryuu import Agent
from ryuu_cognitive.context import CompactionTurn, LLMCompactor
from ryuu_knowledge_memory.tools import MemoryToolset
from ryuu_messaging_core import IncomingMessage, OutgoingMessage, Session, Turn
from ryuu_storage_core import IKVStore

# Models the SuperBot is allowed to use. Tighter than TodoHandler because
# SuperBot does more reasoning-heavy work and the owner pays the bill.
ALLOWED_MODELS = ("gpt-4o-mini", "gpt-4o")
DEFAULT_MODEL = "gpt-4o-mini"

_TRACE_BUDGET = 3000   # chars — keep below Telegram 4096 limit
_MEMORY_BUDGET_TOKENS = 2000   # context space reserved for memory recall

# RYUU_INSTRUCTIONS = soul prompt loaded from markdown. Edit
# examples/ryuu_sensei/prompts/ryuu/v1.md (or shadow via ~/.ryuu/prompts/
# ryuu/v1.md) to tune personality without redeploying code.
#
# Why .md not YAML: soul is prose-heavy. Markdown is the native format for
# human-readable personality docs. YAML is for structured prompts with
# system+user+tools schema (see PromptRegistry).

_FALLBACK_SOUL = (
    "You are Ryuu Sensei (流先生), a private personal assistant. "
    "Be concise. Speak the user's language. Default to Vietnamese if unclear."
)


def _load_soul(version: str = "v1") -> str:
    """Load soul markdown via layered overlay (first match wins):
      1. env var RYUU_SOUL_PATH (explicit path)
      2. ~/.ryuu/prompts/ryuu/<version>.md (user override)
      3. examples/ryuu_sensei/prompts/ryuu/<version>.md (bundled default)
      4. _FALLBACK_SOUL (safety net)

    Soul = personality / values / boundaries / continuity (OpenClaw pattern).
    Memory tools (`remember`/`recall`/`list_memories`) auto-inject via
    tool_registry — no usage instructions needed in prompt. The "Tools
    available" section in the .md is LLM-context only, not directive.
    """
    env_path = os.getenv("RYUU_SOUL_PATH", "").strip()
    if env_path:
        p = Path(env_path).expanduser()
        if p.exists():
            return p.read_text(encoding="utf-8")

    user_path = Path.home() / ".ryuu" / "prompts" / "ryuu" / f"{version}.md"
    if user_path.exists():
        return user_path.read_text(encoding="utf-8")

    bundled = Path(__file__).parent.parent / "prompts" / "ryuu" / f"{version}.md"
    if bundled.exists():
        return bundled.read_text(encoding="utf-8")

    return _FALLBACK_SOUL


RYUU_INSTRUCTIONS = _load_soul()


# ---------------------------------------------------------------------------
# Per-scope settings + stats (same pattern as TodoHandler)
# ---------------------------------------------------------------------------

@dataclass
class UserSettings:
    verbose: bool = False
    model: str = DEFAULT_MODEL
    auto_compact: bool = True                  # Phase 9.0c — auto-shrink long history
    compact_threshold_tokens: int = 4000        # When estimated tokens exceed this


@dataclass
class SessionStats:
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_usd: float = 0.0

    def update_from(self, cost: Any) -> None:
        self.turns += 1
        self.input_tokens += int(getattr(cost, "input_tokens", 0) or 0)
        self.output_tokens += int(getattr(cost, "output_tokens", 0) or 0)
        self.total_usd += float(getattr(cost, "usd", 0.0) or 0.0)


# ---------------------------------------------------------------------------
# Trace capture for /verbose mode — same as TodoHandler
# ---------------------------------------------------------------------------

class TraceCapture:
    def __init__(self) -> None:
        self.lines: list[str] = []

    async def on_thought(self, text: str) -> None:
        if text.strip():
            self.lines.append(f"💭 {text.strip()[:200]}")

    async def on_action(self, tool_name: str, args: dict[str, Any]) -> None:
        self.lines.append(f"🔧 {tool_name}({json.dumps(args, ensure_ascii=False)[:120]})")

    async def on_observation(self, tool_name: str, result: str) -> None:
        preview = result if len(result) <= 200 else result[:197] + "…"
        self.lines.append(f"📋 {preview}")

    async def on_final(self, text: str) -> None:
        pass   # final goes in the main reply

    def render(self) -> str:
        body = "\n".join(self.lines)
        if len(body) > _TRACE_BUDGET:
            body = body[:_TRACE_BUDGET] + "\n…(truncated)"
        return body


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

@dataclass
class RyuuHandler:
    """SuperBot generalist handler. Wires MemoryBackbone + JSONL persistence."""

    # MUST be injected at construction (MemoryBackbone is heavy to build)
    memory_backbone: Any = None    # ryuu_knowledge_memory.MemoryBackbone

    # Optional — providing both enables LLM-based conversation compaction.
    # Without these, auto_compact is silently a no-op (LLMCompactor unbuilt).
    compaction_provider: Any = None   # ryuu_providers_core.ILLMProvider
    prompt_registry: Any = None        # ryuu_prompts.PromptRegistry

    # Phase 8.10 — MCP toolset for external skills (filesystem, GitHub, etc).
    # If provided, MCP tools are merged with memory tools when building agents.
    mcp_toolset: Any = None    # ryuu_mcp_client.MCPToolset

    history_turns: int = 10        # recent session turns to inject in prompt
    include_forget_tool: bool = False  # opt-in destructive memory tool
    compact_keep_recent: int = 5      # turns preserved verbatim when compacting

    # Phase 9.0d.2 — warm-start pre-injects last N memory observations into
    # the prompt (no query-specific search). Lets LLM see "what we know about
    # user" without spending a recall tool call for obvious cases. Set to 0
    # to disable warm-start entirely (LLM calls recall() when it decides).
    #
    # Why no preprocessing pipeline:
    #   ryuu.Agent runs a ReAct loop with recall/remember tools. The LLM
    #   naturally decomposes compound queries via parallel tool_use. Adding
    #   pre-LLM expansion/decomposition stages on top is redundant for
    #   agent-based handlers. (Pipeline still useful for non-agent / RAG /
    #   batch / cost-capped use cases — see ryuu_cognitive.recall.)
    warm_start_top_k: int = 3

    # Per-scope state (single-tenant, so usually just "owner" → values)
    settings: dict[str, UserSettings] = field(default_factory=dict)
    stats: dict[str, SessionStats] = field(default_factory=dict)
    _agents: dict[tuple[str, bool], Agent] = field(default_factory=dict)
    _toolset: MemoryToolset | None = field(default=None, init=False)
    _compactor: LLMCompactor | None = field(default=None, init=False)
    _last_compaction: dict[str, dict[str, int]] = field(default_factory=dict)

    # Optional persistence — same pattern as TodoHandler
    state_store: IKVStore | None = None
    _state_loaded: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if self.memory_backbone is not None:
            self._toolset = MemoryToolset(
                backbone=self.memory_backbone,
                include_forget=self.include_forget_tool,
            )
        if self.compaction_provider is not None and self.prompt_registry is not None:
            self._compactor = LLMCompactor(
                provider=self.compaction_provider,
                registry=self.prompt_registry,
                threshold_tokens=4000,         # default; per-scope override at call time
                keep_recent_turns=self.compact_keep_recent,
            )

    # ------------------------------------------------------------------ #
    # State persistence (lazy-load + write-through)
    # ------------------------------------------------------------------ #
    async def _load_state(self, scope_key: str) -> None:
        if self.state_store is None or scope_key in self._state_loaded:
            return
        blob = await self.state_store.get(scope_key)
        if blob is not None:
            try:
                d = json.loads(blob)
                if "settings" in d:
                    s = d["settings"]
                    self.settings[scope_key] = UserSettings(
                        verbose=bool(s.get("verbose", False)),
                        model=str(s.get("model", DEFAULT_MODEL)),
                        auto_compact=bool(s.get("auto_compact", True)),
                        compact_threshold_tokens=int(s.get("compact_threshold_tokens", 4000)),
                    )
                if "stats" in d:
                    self.stats[scope_key] = SessionStats(**d["stats"])
            except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                pass
        self._state_loaded.add(scope_key)

    async def _save_state(self, scope_key: str) -> None:
        if self.state_store is None:
            return
        payload = {
            "settings": asdict(self.settings.get(scope_key, UserSettings())),
            "stats": asdict(self.stats.get(scope_key, SessionStats())),
        }
        await self.state_store.put(scope_key, json.dumps(payload, ensure_ascii=False))

    # ------------------------------------------------------------------ #
    # Settings + stats API
    # ------------------------------------------------------------------ #
    def get_settings(self, scope_key: str) -> UserSettings:
        return self.settings.setdefault(scope_key, UserSettings())

    def get_stats(self, scope_key: str) -> SessionStats:
        return self.stats.setdefault(scope_key, SessionStats())

    async def set_verbose(self, scope_key: str, on: bool) -> UserSettings:
        await self._load_state(scope_key)
        s = self.get_settings(scope_key)
        s.verbose = on
        await self._save_state(scope_key)
        return s

    async def set_model(self, scope_key: str, model: str) -> UserSettings:
        if model not in ALLOWED_MODELS:
            raise ValueError(
                f"Model {model!r} not allowed. Pick one of: {', '.join(ALLOWED_MODELS)}"
            )
        await self._load_state(scope_key)
        s = self.get_settings(scope_key)
        s.model = model
        await self._save_state(scope_key)
        return s

    async def reset_scope(self, scope_key: str) -> None:
        """Wipe session stats. Memory observations PRESERVED — SuperBot's
        whole point is cross-session memory. To wipe memory, the user must
        delete ~/.ryuu/memory/episodic/<scope>.jsonl explicitly."""
        self.stats.pop(scope_key, None)
        self._state_loaded.discard(scope_key)
        await self._save_state(scope_key)

    async def set_auto_compact(self, scope_key: str, on: bool) -> UserSettings:
        """Toggle auto-compaction for one scope."""
        await self._load_state(scope_key)
        s = self.get_settings(scope_key)
        s.auto_compact = on
        await self._save_state(scope_key)
        return s

    async def set_compact_threshold(self, scope_key: str, threshold: int) -> UserSettings:
        """Set the token threshold above which auto-compact triggers."""
        if threshold < 500:
            raise ValueError(f"Threshold {threshold} too low — minimum 500 tokens.")
        if threshold > 100_000:
            raise ValueError(f"Threshold {threshold} too high — maximum 100000 tokens.")
        await self._load_state(scope_key)
        s = self.get_settings(scope_key)
        s.compact_threshold_tokens = threshold
        await self._save_state(scope_key)
        return s

    async def manual_compact(self, scope_key: str, session: Session) -> dict[str, int]:
        """Force compaction NOW regardless of threshold. Returns stats.

        Returns: {"before": N, "after": M, "saved_turns": N-M}.
        No-op if compactor unavailable, or history too short to compact.
        """
        if self._compactor is None:
            return {"error": -1}
        if len(session.history) <= self.compact_keep_recent:
            return {"before": len(session.history), "after": len(session.history), "saved_turns": 0}
        before = len(session.history)
        await self._compact_session_history(scope_key, session)
        after = len(session.history)
        return {"before": before, "after": after, "saved_turns": before - after}

    async def _compact_session_history(self, scope_key: str, session: Session) -> None:
        """Run LLM compaction + replace session.history with compacted version.

        Records the {before, after} in self._last_compaction for /status display.
        """
        assert self._compactor is not None
        before = len(session.history)
        compaction_history = [
            CompactionTurn(role=t.role, text=t.text) for t in session.history
        ]
        compacted = await self._compactor.compact(compaction_history)
        session.history = [
            Turn(role=t.role, text=t.text) for t in compacted
        ]
        after = len(session.history)
        self._last_compaction[scope_key] = {
            "before": before,
            "after": after,
            "saved_turns": before - after,
        }

    # ------------------------------------------------------------------ #
    # Agent factory — cache per (model, verbose). Each agent has memory tools.
    # ------------------------------------------------------------------ #
    def _get_agent(self, settings: UserSettings) -> Agent:
        key = (settings.model, settings.verbose)
        agent = self._agents.get(key)
        if agent is None:
            # Memory tools (framework primitives) + MCP tools (external skills)
            tools: list[Any] = []
            if self._toolset is not None:
                tools.extend(self._toolset.tools)
            if self.mcp_toolset is not None:
                tools.extend(self.mcp_toolset.tools)
            agent = Agent(
                model=settings.model,
                instructions=RYUU_INSTRUCTIONS,
                tools=tools,
                budget_usd=1.0,
                max_iterations=4,
                verbose=settings.verbose,
            )
            self._agents[key] = agent
        return agent

    # ------------------------------------------------------------------ #
    # IChannelHandler.handle
    # ------------------------------------------------------------------ #
    async def handle(self, msg: IncomingMessage, session: Session) -> OutgoingMessage:
        scope_key = session.scope_key
        await self._load_state(scope_key)
        settings = self.get_settings(scope_key)
        agent = self._get_agent(settings)

        # Phase 9.0c — auto-compact session history if threshold exceeded.
        # Runs BEFORE prompt assembly so the compacted summary is what the
        # LLM sees this turn (no point compacting AFTER the call).
        if settings.auto_compact and self._compactor is not None and len(session.history) > self.compact_keep_recent:
            # Rough estimate: ~40 tokens per turn (better than nothing)
            est_tokens = sum(len(t.text.split()) for t in session.history) * 4 // 3
            if est_tokens >= settings.compact_threshold_tokens:
                await self._compact_session_history(scope_key, session)

        # 1. Build prompt with: warm-start memory + recent session history + new msg.
        # Warm-start = top-N most recent observations (no query-specific search).
        # Agent's ReAct loop calls `recall(query)` tool for query-specific lookups.
        # See Phase 9.0d.2 notes above — ReAct handles decomposition naturally.
        recall_context = ""
        if self.memory_backbone is not None and self.warm_start_top_k > 0:
            try:
                result = await self.memory_backbone.query(
                    "",   # empty query = recent items
                    scope_key=scope_key,
                    top_k=self.warm_start_top_k,
                )
                if result.results:
                    recall_context = (
                        "What I remember about you (recent):\n"
                        + "\n".join(f"  • {r}" for r in result.results)
                        + "\n\n"
                    )
            except Exception:  # noqa: BLE001 — warm-start failure shouldn't break the turn
                pass

        history_lines: list[str] = []
        for turn in session.recent(self.history_turns):
            history_lines.append(f"  {turn.role}: {turn.text}")
        history_block = (
            "Recent conversation:\n" + "\n".join(history_lines) + "\n\n"
            if history_lines else ""
        )

        prompt_text = (
            recall_context
            + history_block
            + f"User now says: {msg.text}"
        )

        # 2. Optional trace capture for /verbose
        trace: TraceCapture | None = None
        original_callbacks = None
        inner = agent._agent
        if settings.verbose:
            trace = TraceCapture()
            original_callbacks = inner.callbacks
            inner.callbacks = trace  # type: ignore[assignment]

        # 3. Bind memory toolset's scope so tool calls hit the right scope.
        # `async with` handles cleanup even if agent.run() raises.
        try:
            if self._toolset is not None:
                async with self._toolset.bind(scope_key=scope_key):
                    result = await agent.run(
                        message=prompt_text,
                        user_id=msg.sender_id,
                        session_id=msg.conversation_id,
                        domain=msg.channel,
                    )
            else:
                result = await agent.run(
                    message=prompt_text,
                    user_id=msg.sender_id,
                    session_id=msg.conversation_id,
                    domain=msg.channel,
                )
        finally:
            if original_callbacks is not None:
                inner.callbacks = original_callbacks  # type: ignore[assignment]

        final_text = (result.output or "").strip() or "(no response)"

        # 4. Compose reply — trace prefix if verbose
        if trace and trace.lines:
            reply_text = f"{trace.render()}\n\n──────\n{final_text}"
        else:
            reply_text = final_text

        # 5. Update session history + stats
        session.append("user", msg.text)
        session.append("assistant", final_text)
        if result.cost is not None:
            self.get_stats(scope_key).update_from(result.cost)
            await self._save_state(scope_key)

        return OutgoingMessage(
            conversation_id=msg.conversation_id,
            text=reply_text,
            formatting="markdown",
            metadata={
                "cost_usd": getattr(result.cost, "usd", 0.0),
                "model": settings.model,
                "verbose": settings.verbose,
                "scope_key": scope_key,
            },
        )
