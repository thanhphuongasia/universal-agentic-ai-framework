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
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ryuu import Agent
from ryuu_cognitive.context import (
    CompactionTurn,
    LLMCompactor,
    build_prompt_breakdown,
)
from ryuu_knowledge_memory.tools import MemoryToolset
from ryuu_messaging_core import IncomingMessage, OutgoingMessage, Session, Turn
from ryuu_storage_core import IKVStore, IProfileStore

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

_DEFAULT_TIER_MODELS: dict[str, str] = {
    "trivial": "gpt-4o-mini",
    "medium":  "gpt-4o-mini",
    "hard":    "gpt-4o",
}


@dataclass
class UserSettings:
    verbose: bool = False
    model: str = DEFAULT_MODEL
    auto_compact: bool = True                  # Phase 9.0c — auto-shrink long history
    compact_threshold_tokens: int = 4000        # When estimated tokens exceed this
    adaptive_routing: bool = False             # auto-select model tier per query difficulty
    streaming: bool = False                    # stream ReAct thoughts in real-time


@dataclass
class SessionStats:
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_usd: float = 0.0
    # Last-turn snapshot — reset on every turn so /last shows the most recent call
    last_model: str = ""
    last_input_tokens: int = 0
    last_output_tokens: int = 0
    last_cost_usd: float = 0.0
    # Per-component prompt token estimate (chars/4 heuristic) so users can trace
    # WHERE their input tokens go. Sum is approximate — real LLM call also
    # includes tool schemas + framework overhead which we don't see here.
    last_breakdown: dict[str, int] = field(default_factory=dict)

    def update_from(self, cost: Any) -> None:
        self.turns += 1
        in_tok = int(getattr(cost, "input_tokens", 0) or 0)
        out_tok = int(getattr(cost, "output_tokens", 0) or 0)
        usd = float(getattr(cost, "usd", 0.0) or 0.0)
        self.input_tokens += in_tok
        self.output_tokens += out_tok
        self.total_usd += usd
        self.last_input_tokens = in_tok
        self.last_output_tokens = out_tok
        self.last_cost_usd = usd


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


class StreamingCallbacks:
    """Callbacks that fire on_event LIVE while agent.run() executes.

    Used by streaming mode to get the best of both worlds: agent.run() returns
    a full AgentResult with cost info, AND on_event fires in real time as the
    ReAct loop progresses (so the UI shows thoughts/tools as they happen).
    """

    def __init__(self, on_event: Callable[[str, str], Awaitable[None]]) -> None:
        self._on_event = on_event

    async def on_thought(self, text: str) -> None:
        if text and text.strip():
            await self._on_event("thought", text)

    async def on_action(self, tool_name: str, args: dict[str, Any]) -> None:
        try:
            args_str = json.dumps(args, ensure_ascii=False)
            if len(args_str) > 200:
                args_str = args_str[:197] + "…"
        except (TypeError, ValueError):
            args_str = str(args)[:200]
        label = f"{tool_name}({args_str})" if args_str else tool_name
        await self._on_event("tool_call", label)

    async def on_observation(self, tool_name: str, result: str) -> None:
        await self._on_event("tool_result", str(result or "")[:300])

    async def on_final(self, text: str) -> None:
        # Pass the final answer so UI can mark "done" if desired. Filtered out
        # in main_ryuu.on_event so it doesn't duplicate the actual reply.
        await self._on_event("final", text or "")

    def render(self) -> str:
        body = "\n".join(self.lines)
        if len(body) > _TRACE_BUDGET:
            body = body[:_TRACE_BUDGET] + "\n…(truncated)"
        return body


# ---------------------------------------------------------------------------
# IHandlerStateStore — backend-agnostic contract for settings + stats
# ---------------------------------------------------------------------------

class IHandlerStateStore(Protocol):
    """Persist UserSettings + SessionStats for one scope.

    Implement this protocol to swap backends without touching RyuuHandler:
        PostgresHandlerStateStore (current) → MySQLHandlerStateStore → RedisHandlerStateStore
    The return type of load() is structurally typed — any object with the
    right fields (model, verbose, …, turns, input_tokens, …) satisfies it.
    """

    async def load(self, scope_key: str) -> Any:
        """Return a HandlerState-shaped object (or defaults if row absent)."""
        ...

    async def save(self, scope_key: str, state: Any) -> None:
        """Persist the full settings + stats for a scope."""
        ...

    async def delete(self, scope_key: str) -> None: ...


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

    # Phase 8.11 — SkillManagerToolset lets the LLM install/uninstall MCP
    # skills via chat. install_skill / uninstall_skill / list_available_skills
    # / list_installed_skills are surfaced as tools to the LLM.
    skill_toolset: Any = None  # ryuu_mcp_client.SkillManagerToolset

    # Phase 8.12 — PromptSkillRegistry (markdown task templates, Claude
    # Code-style). Body is appended to system prompt so the LLM auto-applies
    # them on trigger match. Hot-reload happens on each turn via mtime check.
    prompt_skills: Any = None  # ryuu_prompts.PromptSkillRegistry
    prompt_skills_toolset: Any = None  # ryuu_prompts.PromptSkillsToolset
    system_toolset: Any = None         # examples.ryuu_sensei.apps.system_tools.SystemToolset

    history_turns: int = 10        # recent session turns to inject in prompt
    include_forget_tool: bool = False  # opt-in destructive memory tool
    compact_keep_recent: int = 5      # turns preserved verbatim when compacting

    # Adaptive model routing — maps difficulty tier → model name.
    # difficulty_fn: None → use keyword heuristic from AdaptiveStrategy.
    # Inject a lambda for tests or LLM-based classifier.
    tier_models: dict[str, str] = field(default_factory=lambda: dict(_DEFAULT_TIER_MODELS))
    difficulty_fn: Callable[[str], str] | None = None

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

    # Optional persistence — IKVStore (SQLite blob) or IHandlerStateStore (normalized).
    # normalized_state_store takes precedence when both are provided.
    state_store: IKVStore | None = None
    normalized_state_store: IHandlerStateStore | None = None
    profile_store: IProfileStore | None = None
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
        # Phase 8.11 — listen for MCP toolset changes (install/uninstall via
        # chat) so cached Agents are rebuilt with the new tool list.
        if self.mcp_toolset is not None and hasattr(self.mcp_toolset, "add_listener"):
            self.mcp_toolset.add_listener(self._on_mcp_tools_changed)

    def _on_mcp_tools_changed(self, _toolset: Any) -> None:
        """Drop cached Agent instances — next turn rebuilds with fresh tool list."""
        self._agents.clear()

    # ------------------------------------------------------------------ #
    # State persistence (lazy-load + write-through)
    # ------------------------------------------------------------------ #
    async def _load_state(self, scope_key: str) -> None:
        if scope_key in self._state_loaded:
            return
        if self.normalized_state_store is not None:
            from ryuu_storage_postgres.handler_state import HandlerState
            state: HandlerState = await self.normalized_state_store.load(scope_key)
            self.settings[scope_key] = UserSettings(
                verbose=state.verbose,
                model=state.model,
                auto_compact=state.auto_compact,
                compact_threshold_tokens=state.compact_threshold_tokens,
                adaptive_routing=state.adaptive_routing,
                streaming=getattr(state, "streaming", False),
            )
            self.stats[scope_key] = SessionStats(
                turns=state.turns,
                input_tokens=state.input_tokens,
                output_tokens=state.output_tokens,
                total_usd=state.total_usd,
            )
        elif self.state_store is not None:
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
                            adaptive_routing=bool(s.get("adaptive_routing", False)),
                            streaming=bool(s.get("streaming", False)),
                        )
                    if "stats" in d:
                        self.stats[scope_key] = SessionStats(**d["stats"])
                except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                    pass
        self._state_loaded.add(scope_key)

    async def _save_state(self, scope_key: str) -> None:
        if self.normalized_state_store is not None:
            from ryuu_storage_postgres.handler_state import HandlerState
            s = self.settings.get(scope_key, UserSettings())
            st = self.stats.get(scope_key, SessionStats())
            await self.normalized_state_store.save(scope_key, HandlerState(
                model=s.model,
                verbose=s.verbose,
                auto_compact=s.auto_compact,
                compact_threshold_tokens=s.compact_threshold_tokens,
                adaptive_routing=s.adaptive_routing,
                streaming=s.streaming,
                turns=st.turns,
                input_tokens=st.input_tokens,
                output_tokens=st.output_tokens,
                total_usd=st.total_usd,
            ))
        elif self.state_store is not None:
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

    async def set_adaptive_routing(self, scope_key: str, on: bool) -> UserSettings:
        """Toggle adaptive model routing for one scope."""
        await self._load_state(scope_key)
        s = self.get_settings(scope_key)
        s.adaptive_routing = on
        await self._save_state(scope_key)
        return s

    async def set_streaming(self, scope_key: str, on: bool) -> UserSettings:
        """Toggle streaming mode (live ReAct thought display) for one scope."""
        await self._load_state(scope_key)
        s = self.get_settings(scope_key)
        s.streaming = on
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
    # Adaptive routing — select effective model for this turn
    # ------------------------------------------------------------------ #
    def _select_model(self, text: str, settings: UserSettings) -> str:
        """Return the model to use for this turn.

        When adaptive_routing=False, returns settings.model unchanged.
        When True, classifies query difficulty and maps to tier_models.
        Falls back to settings.model if the tier candidate is not in ALLOWED_MODELS.
        """
        if not settings.adaptive_routing:
            return settings.model
        if self.difficulty_fn is None:
            raise ValueError(
                "adaptive_routing=True requires difficulty_fn on RyuuHandler. "
                "Pass difficulty_fn=<callable str->'trivial'|'medium'|'hard'>."
            )
        difficulty = self.difficulty_fn(text)
        candidate = self.tier_models.get(difficulty, settings.model)
        return candidate if candidate in ALLOWED_MODELS else settings.model

    # ------------------------------------------------------------------ #
    # Agent factory — cache per (model, verbose). Each agent has memory tools.
    # ------------------------------------------------------------------ #
    def _build_instructions(self) -> str:
        """Soul prose + prompt-skill catalog (if registry wired).

        NOTE: We tried adding a "narrate before tool use" instruction to populate
        the LLM response.content (for streaming UX), but it caused gpt-4o-mini
        to skip tool calls entirely — it would just describe what it WOULD do
        instead of doing it. Reverted. The framework's generic "I'll use X to
        gather data" placeholder is filtered out client-side instead.
        """
        base = RYUU_INSTRUCTIONS
        if self.prompt_skills is not None and len(self.prompt_skills) > 0:
            skill_block = self.prompt_skills.render_context()
            if skill_block:
                return base + "\n\n" + skill_block
        return base

    def _get_agent(self, settings: UserSettings, model_override: str | None = None) -> Agent:
        model = model_override or settings.model
        key = (model, settings.verbose)
        agent = self._agents.get(key)
        if agent is None:
            # Memory tools (framework primitives) + MCP tools (external skills)
            # + skill management tools (install/uninstall MCP skills via chat)
            # + prompt-skills inspection tools (list/reload markdown task patterns)
            tools: list[Any] = []
            if self._toolset is not None:
                tools.extend(self._toolset.tools)
            if self.mcp_toolset is not None:
                tools.extend(self.mcp_toolset.tools)
            if self.skill_toolset is not None:
                tools.extend(self.skill_toolset.tools)
            if self.prompt_skills_toolset is not None:
                tools.extend(self.prompt_skills_toolset.tools)
            if self.system_toolset is not None:
                tools.extend(self.system_toolset.tools)
            agent = Agent(
                model=model,
                instructions=self._build_instructions(),
                tools=tools,
                budget_usd=1.0,
                max_iterations=4,
                verbose=settings.verbose,
            )
            self._agents[key] = agent
        return agent

    # ------------------------------------------------------------------ #
    # Streaming helper — agent.stream() + memory toolset binding
    # ------------------------------------------------------------------ #
    async def _run_streaming(
        self,
        agent: Agent,
        prompt_text: str,
        msg: IncomingMessage,
        scope_key: str,
        on_event: Callable[[str, str], Awaitable[None]],
    ) -> str:
        """Run agent in streaming mode. Calls on_event(type, text) for each step.

        Returns the final answer text. Cost is not tracked (stream() doesn't
        expose AgentResult). Memory toolset binding is held open for the full
        stream so recall/remember tool calls work correctly.
        """
        final_text = ""

        async def _consume() -> None:
            nonlocal final_text
            async for event in agent.stream(
                message=prompt_text,
                user_id=msg.sender_id,
                session_id=msg.conversation_id,
                domain=msg.channel,
            ):
                if event.type == "thought" and event.text:
                    await on_event("thought", event.text)
                elif event.type == "tool_call" and event.tool_name:
                    # Pack tool name + args into single text so UX sees what
                    # the LLM is actually calling, not just the function name.
                    args_str = ""
                    if event.args:
                        try:
                            args_str = json.dumps(event.args, ensure_ascii=False)
                            if len(args_str) > 200:
                                args_str = args_str[:197] + "…"
                        except (TypeError, ValueError):
                            args_str = str(event.args)[:200]
                    label = f"{event.tool_name}({args_str})" if args_str else event.tool_name
                    await on_event("tool_call", label)
                elif event.type == "tool_result":
                    await on_event("tool_result", str(event.result or "")[:300])
                elif event.type == "final":
                    final_text = event.text

        if self._toolset is not None:
            async with self._toolset.bind(scope_key=scope_key):
                await _consume()
        else:
            await _consume()

        return (final_text or "(no response)").strip()

    # ------------------------------------------------------------------ #
    # IChannelHandler.handle
    # ------------------------------------------------------------------ #
    async def handle(
        self,
        msg: IncomingMessage,
        session: Session,
        on_event: Callable[[str, str], Awaitable[None]] | None = None,
    ) -> OutgoingMessage:
        """Handle one turn. on_event: optional streaming callback (type, text) ->
        None, called for each thought/tool_call/tool_result during agent.stream().
        Only active when settings.streaming=True AND on_event is provided.
        """
        scope_key = session.scope_key
        await self._load_state(scope_key)
        settings = self.get_settings(scope_key)

        # Phase 8.12 — hot-reload prompt skills if any .md file changed. Cheap
        # mtime check per turn; only re-scans on actual change. Cache is then
        # cleared so the next _get_agent rebuilds with refreshed catalog.
        if self.prompt_skills is not None:
            if self.prompt_skills.reload_if_changed() > 0:
                self._agents.clear()

        effective_model = self._select_model(msg.text, settings)
        agent = self._get_agent(settings, model_override=effective_model)

        # Phase 9.0c — auto-compact session history if threshold exceeded.
        # Runs BEFORE prompt assembly so the compacted summary is what the
        # LLM sees this turn (no point compacting AFTER the call).
        # Uses the LAST turn's actual measured input_tokens — far more accurate
        # than text.split() which misses system prompt + memory + profile blocks.
        if (
            settings.auto_compact
            and self._compactor is not None
            and len(session.history) > self.compact_keep_recent
        ):
            stats = self.get_stats(scope_key)
            last_tokens = stats.last_input_tokens
            # Fallback estimate on first turn (no measurement yet): scale by history
            if last_tokens == 0:
                last_tokens = sum(len(t.text.split()) for t in session.history) * 4 // 3
            if last_tokens >= settings.compact_threshold_tokens:
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

        # Drain steer messages from ScopeDispatcher (optional).
        # live_steer: messages injected while the CURRENT task was running
        # carry_steer: messages that arrived during the PREVIOUS task but
        #   couldn't be applied mid-generation; carried forward by orchestrator
        steer_block = ""
        disp_state = session.extra.get("_dispatcher_state")
        steer_ctx = disp_state.steer_ctx if disp_state is not None else session.extra.get("_steer_ctx")
        live_steer = steer_ctx.drain() if steer_ctx is not None else []
        carry_steer: list[str] = session.extra.pop("_carry_steer", [])
        all_steer = live_steer + carry_steer
        if all_steer:
            steer_block = (
                "Additional context from user while I was working:\n"
                + "\n".join(f"  • {s}" for s in all_steer)
                + "\n\n"
            )

        profile_block = ""
        if self.profile_store is not None:
            try:
                pb = await self.profile_store.as_prompt_block(scope_key)
                if pb:
                    profile_block = pb + "\n\n"
            except Exception:  # noqa: BLE001 — profile failure never breaks a turn
                pass

        prompt_text = (
            profile_block
            + recall_context
            + history_block
            + steer_block
            + f"User now says: {msg.text}"
        )

        # Track WHERE this turn's tokens come from. Stored on stats so /last
        # and /status can surface it. Framework helper handles the estimation
        # (chars/4) — tool schemas + framework overhead aren't visible here.
        breakdown = build_prompt_breakdown({
            "system":   self._build_instructions(),
            "memory":   recall_context,
            "history":  history_block,
            "profile":  profile_block,
            "steer":    steer_block,
            "user_msg": msg.text,
        })

        use_streaming = settings.streaming and on_event is not None

        # 2. Callbacks setup:
        #    - streaming: StreamingCallbacks fires on_event live during agent.run()
        #    - verbose (non-streaming): TraceCapture collects trace for trailing display
        trace: TraceCapture | None = None
        original_callbacks = None
        inner = agent._agent
        if use_streaming:
            assert on_event is not None
            original_callbacks = inner.callbacks
            inner.callbacks = StreamingCallbacks(on_event)  # type: ignore[assignment]
        elif settings.verbose:
            trace = TraceCapture()
            original_callbacks = inner.callbacks
            inner.callbacks = trace  # type: ignore[assignment]

        # 3. Execute — always use agent.run() so we always get cost/usage back.
        # StreamingCallbacks (set above) drives the live UI updates via on_event.
        result_cost: Any = None
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
            final_text = (result.output or "").strip() or "(no response)"
            result_cost = result.cost
        finally:
            if original_callbacks is not None:
                inner.callbacks = original_callbacks  # type: ignore[assignment]

        # 4. Compose reply — trace prefix if verbose (non-streaming only)
        if trace and trace.lines:
            reply_text = f"{trace.render()}\n\n──────\n{final_text}"
        else:
            reply_text = final_text

        # 5. Update session history + stats
        session.append("user", msg.text)
        session.append("assistant", final_text)
        stats = self.get_stats(scope_key)
        stats.last_model = effective_model  # always record model used, even if no cost
        stats.last_breakdown = breakdown    # always record prompt breakdown
        if result_cost is not None:
            stats.update_from(result_cost)
            await self._save_state(scope_key)

        return OutgoingMessage(
            conversation_id=msg.conversation_id,
            text=reply_text,
            formatting="markdown",
            metadata={
                "cost_usd": getattr(result_cost, "usd", 0.0),
                "model": effective_model,
                "adaptive": settings.adaptive_routing,
                "verbose": settings.verbose,
                "scope_key": scope_key,
            },
        )
