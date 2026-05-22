"""TodoHandler — Layer 3, implements IChannelHandler.

Owns:
  • the ryuu.Agent (built lazily per (model, verbose) combo and cached)
  • per-scope settings (model, verbose)
  • per-scope running stats (turns, tokens, USD cost)
  • a TraceCapture callback that mirrors LLM Thought/Action/Observation
    back into the chat when verbose is on

Does NOT own:
  • session history (lives on Session object, owned by ConversationManager)
  • channel transport (Adapter's job)
  • scope resolution (IScopeResolver's job)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from ryuu import Agent
from ryuu_storage_core import IKVStore

from ryuu_messaging_core import (
    IncomingMessage,
    OutgoingMessage,
    Session,
    Turn,
)

from examples.ryuu_sensei.apps.todo_tools import (
    TODO_TOOLS,
    reset_current_user,
    set_current_user,
)

# Models users are allowed to switch to. Narrow allowlist = fewer provider
# auto-detect failure modes at runtime.
ALLOWED_MODELS = ("gpt-4o-mini", "gpt-4o", "gpt-4o-mini-2024-07-18")
DEFAULT_MODEL = "gpt-4o-mini"

# Telegram message size limit is 4096 chars. Reserve headroom for Final answer.
_TRACE_BUDGET = 3000

TODO_INSTRUCTIONS = (
    "You are Ryuu Sensei (流先生), a personal todo assistant. "
    "Use the provided tools to add, list, complete, and delete todos when "
    "the user asks. Always confirm what you did. Keep replies under 60 words. "
    "If the user mentions a todo number, prefer using the tools over guessing."
)


# ---------------------------------------------------------------------------
# Per-scope settings + running stats
# ---------------------------------------------------------------------------

@dataclass
class UserSettings:
    verbose: bool = False
    model: str = DEFAULT_MODEL


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
# ReAct trace capture — fed to the user when /verbose on
# ---------------------------------------------------------------------------

class TraceCapture:
    """Buffer ReActCallbacks events so we can mirror them into the chat."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    async def on_thought(self, text: str) -> None:
        if text.strip():
            self.lines.append(f"💭 {text.strip()[:200]}")

    async def on_action(self, tool_name: str, args: dict[str, Any]) -> None:
        self.lines.append(f"🔧 {tool_name}({json.dumps(args, ensure_ascii=False)})")

    async def on_observation(self, tool_name: str, result: str) -> None:
        preview = result if len(result) <= 200 else result[:197] + "…"
        self.lines.append(f"📋 {preview}")

    async def on_final(self, text: str) -> None:
        # Final is delivered as the main reply — no need to mirror.
        pass

    def render(self) -> str:
        body = "\n".join(self.lines)
        if len(body) > _TRACE_BUDGET:
            body = body[:_TRACE_BUDGET] + "\n…(truncated)"
        return body


# ---------------------------------------------------------------------------
# Helper — format prior turns into the prompt text (factory Agent is single-shot)
# ---------------------------------------------------------------------------

def _format_history(history: list[Turn], new_message: str) -> str:
    if not history:
        return new_message
    lines = ["Previous conversation:"]
    for turn in history:
        lines.append(f"  {turn.role}: {turn.text}")
    lines.append(f"\nUser now says: {new_message}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

@dataclass
class TodoHandler:
    """Implements IChannelHandler.handle(msg, session) -> OutgoingMessage."""

    history_turns: int = 10
    settings: dict[str, UserSettings] = field(default_factory=dict)
    stats: dict[str, SessionStats] = field(default_factory=dict)
    _agents: dict[tuple[str, bool], Agent] = field(default_factory=dict)

    # Optional persistence — pass an IKVStore (e.g. SqliteKVStore) to survive
    # restarts. Keys inside the store are bare scope_keys. Values are JSON:
    #   {"settings": {"model": "...", "verbose": false}, "stats": {...}}
    state_store: IKVStore | None = None
    _state_loaded: set[str] = field(default_factory=set)

    # ------------------------------------------------------------------ #
    # State persistence — lazy-load on first access, write through on mutate
    # ------------------------------------------------------------------ #
    async def _load_state(self, scope_key: str) -> None:
        if self.state_store is None or scope_key in self._state_loaded:
            return
        blob = await self.state_store.get(scope_key)
        if blob is not None:
            try:
                data = json.loads(blob)
                s = data.get("settings", {})
                if s:
                    self.settings[scope_key] = UserSettings(
                        verbose=bool(s.get("verbose", False)),
                        model=str(s.get("model", DEFAULT_MODEL)),
                    )
                st = data.get("stats", {})
                if st:
                    self.stats[scope_key] = SessionStats(
                        turns=int(st.get("turns", 0)),
                        input_tokens=int(st.get("input_tokens", 0)),
                        output_tokens=int(st.get("output_tokens", 0)),
                        total_usd=float(st.get("total_usd", 0.0)),
                    )
            except (json.JSONDecodeError, KeyError, ValueError):
                pass  # corrupt row — fall through with defaults
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
    # Settings API — keyed by scope_key (NOT sender_id directly)
    # ------------------------------------------------------------------ #
    def get_settings(self, scope_key: str) -> UserSettings:
        return self.settings.setdefault(scope_key, UserSettings())

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

    def get_stats(self, scope_key: str) -> SessionStats:
        return self.stats.setdefault(scope_key, SessionStats())

    async def reset_scope(self, scope_key: str) -> None:
        """Wipe handler-side stats for one scope. Called by /clear callback in
        addition to ConversationManager.clear (which wipes Session).

        Settings intentionally kept — clearing conversation shouldn't reset
        model choice.

        Bug fix (was sync, only wiped in-memory): also evicts the load-once
        cache and writes the now-empty state to DB. Without this, a restart
        after /clear would reload the OLD stats from SQLite.
        """
        self.stats.pop(scope_key, None)
        self._state_loaded.discard(scope_key)
        await self._save_state(scope_key)

    # ------------------------------------------------------------------ #
    # Agent factory — cache by (model, verbose)
    # ------------------------------------------------------------------ #
    def _get_agent(self, settings: UserSettings) -> Agent:
        key = (settings.model, settings.verbose)
        agent = self._agents.get(key)
        if agent is None:
            agent = Agent(
                model=settings.model,
                instructions=TODO_INSTRUCTIONS,
                tools=TODO_TOOLS,
                budget_usd=1.0,
                max_iterations=4,
                verbose=settings.verbose,
            )
            self._agents[key] = agent
        return agent

    # ------------------------------------------------------------------ #
    # IChannelHandler.handle — the only method adapters/orchestrator call
    # ------------------------------------------------------------------ #
    async def handle(self, msg: IncomingMessage, session: Session) -> OutgoingMessage:
        scope_key = session.scope_key
        await self._load_state(scope_key)
        settings = self.get_settings(scope_key)
        agent = self._get_agent(settings)

        # Build context-aware prompt from session history
        history = session.recent(self.history_turns)
        prompt_text = _format_history(history, msg.text)

        # Optional trace capture for /verbose mode
        trace: TraceCapture | None = None
        original_callbacks = None
        inner = agent._agent  # _FactoryLLMAgent — has .callbacks attr
        if settings.verbose:
            trace = TraceCapture()
            original_callbacks = inner.callbacks
            inner.callbacks = trace  # type: ignore[assignment]

        # Bind the user contextvar so todo tools see the right user_id.
        # Tools key the todo store by sender_id directly (not scope) so the
        # same Telegram user with different scope strategies still gets a
        # coherent list.
        token = set_current_user(msg.sender_id)
        try:
            result = await agent.run(
                message=prompt_text,
                user_id=msg.sender_id,
                session_id=msg.conversation_id,
                domain=msg.channel,
            )
        finally:
            reset_current_user(token)
            if original_callbacks is not None:
                inner.callbacks = original_callbacks  # type: ignore[assignment]

        final_text = (result.output or "").strip() or "(no response)"

        # Mirror trace into the reply when verbose is on
        if trace and trace.lines:
            reply_text = f"{trace.render()}\n\n──────\n{final_text}"
        else:
            reply_text = final_text

        # Update Session history — note we store the bare msg.text and final
        # answer only, NOT the trace prefix (keeps future prompts clean)
        session.append("user", msg.text)
        session.append("assistant", final_text)

        # Update running stats + persist
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
