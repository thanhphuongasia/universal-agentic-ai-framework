"""TodoSensei — RyuuSensei wired up with the todo app's tools.

On top of the base RyuuSensei, this subclass adds:
  • per-user settings (verbose on/off, model selection)
  • per-(model, verbose) cached ryuu.Agent instances
  • Telegram-facing trace capture (Thought/Action/Observation pushed back to
    the user when /verbose is on)
  • a user contextvar so the todo tools see the right user_id
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ryuu import Agent

from examples.ryuu_sensei.apps.todo_tools import (
    TODO_TOOLS,
    reset_current_user,
    set_current_user,
)
from examples.ryuu_sensei.messages import IncomingMessage, OutgoingMessage
from examples.ryuu_sensei.sensei import RyuuSensei, _format_history
from examples.ryuu_sensei.session import make_session_key

# Models users are allowed to switch to. Keep narrow — wider list = more ways
# the LLM provider auto-detect can fail at runtime.
ALLOWED_MODELS = ("gpt-4o-mini", "gpt-4o", "gpt-4o-mini-2024-07-18")
DEFAULT_MODEL = "gpt-4o-mini"

# Telegram message size limit is 4096 chars. Reserve headroom for the final
# answer + separator + the trace prefix block.
_TRACE_BUDGET = 3000

TODO_INSTRUCTIONS = (
    "You are Ryuu Sensei (流先生), a personal todo assistant. "
    "Use the provided tools to add, list, complete, and delete todos when "
    "the user asks. Always confirm what you did. Keep replies under 60 words. "
    "If the user mentions a todo number, prefer using the tools over guessing."
)


# ---------------------------------------------------------------------------
# Per-user settings
# ---------------------------------------------------------------------------

@dataclass
class UserSettings:
    verbose: bool = False
    model: str = DEFAULT_MODEL


@dataclass
class SessionStats:
    """Running totals per session (NOT per agent.run() call).

    Populated from the `Cost` object that every ryuu.Agent.run() returns
    via result.cost. This is the same source the framework's CostTracker
    consumes — we just aggregate it ourselves for chat display.
    """
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
        # Skip — the final answer is sent separately as the main reply.
        pass

    def render(self) -> str:
        body = "\n".join(self.lines)
        if len(body) > _TRACE_BUDGET:
            body = body[:_TRACE_BUDGET] + "\n…(truncated)"
        return body


# ---------------------------------------------------------------------------
# Sensei
# ---------------------------------------------------------------------------

@dataclass
class TodoSensei(RyuuSensei):
    name: str = "Ryuu Todo Sensei"

    settings: dict[str, UserSettings] = field(default_factory=dict)
    stats: dict[str, SessionStats] = field(default_factory=dict)
    _agents: dict[tuple[str, bool], Agent] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Skip the parent's default Agent build — we manage agents ourselves
        # keyed by user settings. `self.agent` stays as the user-supplied
        # default (used when no per-user override exists; can be None).
        pass

    # ------------------------------------------------------------------ #
    # Settings API — called by channel adapters' command handlers
    # ------------------------------------------------------------------ #
    def get_settings(self, channel: str, user_id: str) -> UserSettings:
        key = make_session_key(channel, user_id)
        return self.settings.setdefault(key, UserSettings())

    def set_verbose(self, channel: str, user_id: str, on: bool) -> UserSettings:
        s = self.get_settings(channel, user_id)
        s.verbose = on
        return s

    def set_model(self, channel: str, user_id: str, model: str) -> UserSettings:
        if model not in ALLOWED_MODELS:
            raise ValueError(
                f"Model {model!r} not allowed. Pick one of: {', '.join(ALLOWED_MODELS)}"
            )
        s = self.get_settings(channel, user_id)
        s.model = model
        return s

    def get_stats(self, channel: str, user_id: str) -> SessionStats:
        key = make_session_key(channel, user_id)
        return self.stats.setdefault(key, SessionStats())

    def context_size(self, channel: str, user_id: str) -> int:
        """Number of turns currently in the short-term buffer."""
        key = make_session_key(channel, user_id)
        return len(self.sessions.recent(key))

    # ------------------------------------------------------------------ #
    # Agent factory — cache by (model, verbose) so we don't rebuild per turn
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
    # Core handler — overrides parent. Per-user agent + contextvar + trace.
    # ------------------------------------------------------------------ #
    async def handle_message(self, msg: IncomingMessage) -> OutgoingMessage:
        session_key = make_session_key(msg.channel, msg.user_id)
        settings = self.get_settings(msg.channel, msg.user_id)
        agent = self._get_agent(settings)

        # Build context-aware prompt (recent turns + new message)
        history = self.sessions.recent(session_key, n=self.history_turns)
        prompt_text = _format_history(history, msg.text)

        # Optional trace capture — replace the inner agent's callbacks for
        # the duration of this call so we can mirror events back to chat.
        trace: TraceCapture | None = None
        original_callbacks = None
        inner = agent._agent  # _FactoryLLMAgent — has .callbacks attr
        if settings.verbose:
            trace = TraceCapture()
            original_callbacks = inner.callbacks
            inner.callbacks = trace  # type: ignore[assignment]

        # Bind the user contextvar so todo tools see the right user_id
        token = set_current_user(msg.user_id)
        try:
            result = await agent.run(
                message=prompt_text,
                user_id=msg.user_id,
                session_id=msg.conversation_id,
                domain=msg.channel,
            )
        finally:
            reset_current_user(token)
            if original_callbacks is not None:
                inner.callbacks = original_callbacks  # type: ignore[assignment]

        final_text = (result.output or "").strip() or "(no response)"

        # If verbose, prepend the captured ReAct trace
        if trace and trace.lines:
            reply_text = f"{trace.render()}\n\n──────\n{final_text}"
        else:
            reply_text = final_text

        # Update short-term memory AFTER successful reply (use final only,
        # not the trace, so future prompts stay clean)
        self.sessions.append(session_key, "user", msg.text)
        self.sessions.append(session_key, "assistant", final_text)

        # Update running totals so /status can report cumulative usage
        if result.cost is not None:
            self.stats.setdefault(session_key, SessionStats()).update_from(result.cost)

        return OutgoingMessage(
            conversation_id=msg.conversation_id,
            text=reply_text,
            formatting="markdown",
            metadata={
                "cost_usd": getattr(result.cost, "usd", 0.0),
                "model": settings.model,
                "verbose": settings.verbose,
            },
        )
