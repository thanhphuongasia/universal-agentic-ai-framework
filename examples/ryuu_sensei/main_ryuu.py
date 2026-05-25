"""Ryuu Sensei SuperBot — entry point (Phase 9.0a reference impl).

Single-tenant generalist assistant. Read examples/ryuu_sensei/apps/ryuu_handler.py
for architecture notes.

Differences vs `main.py` (TodoBot demo):
  • SingleTenantResolver instead of DefaultScopeResolver
  • MemoryBackbone wired with JSONL persistence (~/.ryuu/memory/)
  • TelegramAdapter.allowed_senders gate — only owner ID can DM
  • Separate SQLite DB (~/.ryuu/super.db) — doesn't collide with TodoBot

Run:
  export RYUU_BOT_TOKEN='...'
  export OWNER_TELEGRAM_ID='123456789'
  export OPENAI_API_KEY='sk-...'
  python -m examples.ryuu_sensei.main_ryuu                # CLI only
  python -m examples.ryuu_sensei.main_ryuu --telegram     # CLI + Telegram

The owner's Telegram user ID can be obtained by:
  1. Open Telegram, search @userinfobot
  2. Send /start — it replies with your numeric ID
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Any


def _load_dotenv() -> None:
    """Load secrets from ~/.ryuu/.env (or $RYUU_ENV_FILE) into os.environ.

    Persistent secrets (RYUU_BOT_TOKEN, OPENAI_API_KEY, etc.) live in this
    file so the user doesn't have to re-export them every restart. Existing
    env vars take precedence — pre-set vars from the shell are not overwritten.

    Format is the standard one — `KEY=value` per line, blank lines and
    `#` comments skipped, optional surrounding quotes stripped.
    """
    env_path = Path(os.environ.get("RYUU_ENV_FILE", str(Path.home() / ".ryuu" / ".env"))).expanduser()
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # Shell-exported vars win — only fill in missing ones.
        os.environ.setdefault(key, value)


_load_dotenv()

from ryuu_knowledge_memory.backbone import MemoryBackbone
from ryuu_knowledge_memory.episodic import EpisodicMemoryStore
from ryuu_knowledge_memory.working import WorkingMemoryStore
from ryuu_messaging_cli import CLIAdapter
from ryuu_messaging_core import (
    ChannelOrchestrator,
    ConversationManager,
    KVSessionStore,
    MessageClassifier,
    ScopeDispatcher,
    SingleTenantResolver,
    StandardDispatchLogger,
)
from ryuu_mcp_client import (
    MCPSkillsLoader,
    MCPToolset,
    SkillManager,
    SkillManagerToolset,
    SkillRegistry,
)
from ryuu_prompts import (
    PromptSkillRegistry,
    PromptSkillsToolset,
    make_framework_registry,
)
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

if DATABASE_URL:
    from ryuu_storage_postgres import (
        PostgresCollectionStore,
        PostgresHandlerStateStore,
        PostgresKVStore,
        PostgresProfileStore,
        PostgresSessionStore,
    )

    def _kv(table: str):
        return PostgresKVStore(dsn=DATABASE_URL, table=table)

    def _coll(table: str):
        return PostgresCollectionStore(dsn=DATABASE_URL, table=table)

    def _session_store() -> "PostgresSessionStore":
        return PostgresSessionStore(dsn=DATABASE_URL, max_turns=20)

    def _handler_state_store() -> "PostgresHandlerStateStore":
        return PostgresHandlerStateStore(dsn=DATABASE_URL)

    def _profile_store() -> "PostgresProfileStore":
        return PostgresProfileStore(dsn=DATABASE_URL)

else:
    from ryuu_storage_jsonl import JsonlCollectionStore
    from ryuu_storage_sqlite import SqliteKVStore

    def _kv(table: str):
        return SqliteKVStore(db_path=SUPER_DB_PATH, table=table)

    def _coll(table: str):
        return JsonlCollectionStore(root_dir=MEMORY_DIR, table=table)

    def _session_store():
        return None

    def _handler_state_store():
        return None

    def _profile_store():
        return None

from examples.ryuu_sensei.apps.ryuu_handler import ALLOWED_MODELS, RyuuHandler


def _build_compaction_provider():
    """Build an OpenAI provider for the LLMCompactor.

    Returns None if OPENAI_API_KEY missing — auto-compact will be a no-op.
    """
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from ryuu_providers_openai import OpenAIProvider
        return OpenAIProvider(api_key=api_key)
    except ImportError:
        return None


LOG_PATH = Path(os.getenv("RYUU_LOG", str(Path.home() / ".ryuu" / "ryuu.log")))

SUPER_DB_PATH = Path(os.getenv("RYUU_SUPER_DB", str(Path.home() / ".ryuu" / "super.db")))
MEMORY_DIR = Path(os.getenv("RYUU_MEMORY_DIR", str(Path.home() / ".ryuu" / "memory")))
SKILLS_PATH = Path(os.getenv("RYUU_SKILLS_PATH", str(Path.home() / ".ryuu" / "skills.yaml")))
PROMPT_SKILLS_USER_DIR = Path(os.getenv("RYUU_PROMPT_SKILLS_DIR", str(Path.home() / ".ryuu" / "skills")))
PROMPT_SKILLS_BUNDLED_DIR = Path(__file__).parent / "skills"

# Telegram / autocomplete — full command list for this application.
# Add, remove, or override freely. Adapter never hard-codes these.
BOT_COMMANDS: list[tuple[str, str]] = [
    ("help",         "Show available commands"),
    ("status",       "Session totals: token usage, cost, context size"),
    ("last",         "Last-turn: model used, tokens in/out, cost"),
    ("settings",     "Show your current settings"),
    ("clear",        "Forget conversation history"),
    ("model",        "Switch LLM model (inline buttons)"),
    ("verbose",      "verbose on|off — show reasoning trace after reply"),
    ("streaming",    "streaming on|off — stream ReAct thoughts live"),
    ("adaptive",     "adaptive on|off — auto-select model tier per query"),
    ("compact",      "Compact long history now (free up context)"),
    ("auto_compact", "auto_compact on|off — toggle automatic compaction"),
    ("task",         "Show dispatcher task state"),
]


def _build_telegram_callbacks(
    orchestrator: ChannelOrchestrator,
    handler: RyuuHandler,
    cm: ConversationManager,
):
    """Closures bridging Telegram IDs → owner scope → handler state.
    Single-tenant: all calls route to scope_key='owner'."""

    async def on_clear(sender_id: str, conversation_id: str) -> None:
        scope = await orchestrator.clear_scope("telegram", sender_id, conversation_id)
        await handler.reset_scope(scope)

    async def on_verbose(sender_id: str, conversation_id: str, on: bool) -> str:
        scope = await cm.resolve_scope("telegram", sender_id, conversation_id)
        await handler.set_verbose(scope, on)
        return f"Verbose is now **{'on' if on else 'off'}**."

    async def on_model(sender_id: str, conversation_id: str, model: str) -> str:
        scope = await cm.resolve_scope("telegram", sender_id, conversation_id)
        if model == "auto":
            s = await handler.set_adaptive_routing(scope, True)
            return "Model set to **auto** — adaptive routing on, tier selected per query."
        s = await handler.set_model(scope, model)
        if s.adaptive_routing:
            await handler.set_adaptive_routing(scope, False)
            return f"Model fixed to **{s.model}** (adaptive routing off)."
        return f"Model switched to **{s.model}**."

    async def on_settings(sender_id: str, conversation_id: str) -> str:
        scope = await cm.resolve_scope("telegram", sender_id, conversation_id)
        await handler._load_state(scope)
        s = handler.get_settings(scope)
        return (
            "⚙️ Settings\n"
            f"  • model:    {s.model}\n"
            f"  • adaptive: {'on — auto-selects tier per query' if s.adaptive_routing else 'off — fixed model'}\n"
            f"  • verbose:  {'on' if s.verbose else 'off'}\n\n"
            f"Allowed models: {', '.join(ALLOWED_MODELS)}\n"
            "Change via /model, /adaptive on|off, or /verbose on|off"
        )

    async def on_status(sender_id: str, conversation_id: str) -> str:
        scope = await cm.resolve_scope("telegram", sender_id, conversation_id)
        await handler._load_state(scope)
        s = handler.get_settings(scope)
        stats = handler.get_stats(scope)
        session = await cm.session_store.load_or_create(
            scope_key=scope, channel="telegram",
            sender_id=sender_id, conversation_id=conversation_id,
        )
        model_display = "auto" if s.adaptive_routing else s.model
        ac_display = (
            f"on (>{s.compact_threshold_tokens:,} tok)"
            if s.auto_compact else "off"
        )
        bd = stats.last_breakdown
        breakdown_line = ""
        if bd:
            sys_t = bd.get("system", 0)
            mem_t = bd.get("memory", 0)
            hist_t = bd.get("history", 0)
            breakdown_line = (
                f"\n  • last prompt est:  sys={sys_t:,} mem={mem_t:,} hist={hist_t:,}"
                f" (see /last)"
            )
        return (
            "📊 Session status\n"
            f"  • model:           {model_display}\n"
            f"  • verbose:         {'on' if s.verbose else 'off'}\n"
            f"  • streaming:       {'on' if s.streaming else 'off'}\n"
            f"  • auto_compact:    {ac_display}\n"
            f"  • context buffer:  {len(session.history)} / {session.max_turns} turns\n"
            f"  • LLM calls:       {stats.turns}\n"
            f"  • tokens in/out:   {stats.input_tokens:,} / {stats.output_tokens:,}\n"
            f"  • cost so far:     ${stats.total_usd:.6f}"
            + breakdown_line
        )

    async def on_current_model(sender_id: str, conversation_id: str) -> str:
        scope = await cm.resolve_scope("telegram", sender_id, conversation_id)
        await handler._load_state(scope)
        s = handler.get_settings(scope)
        return "auto" if s.adaptive_routing else s.model

    async def on_compact(sender_id: str, conversation_id: str) -> str:
        scope = await cm.resolve_scope("telegram", sender_id, conversation_id)
        if handler._compactor is None:
            return (
                "Compaction unavailable: OPENAI_API_KEY missing or "
                "ryuu-providers-openai not installed."
            )
        session = await cm.session_store.load_or_create(
            scope_key=scope, channel="telegram",
            sender_id=sender_id, conversation_id=conversation_id,
        )
        before = len(session.history)
        stats = await handler.manual_compact(scope, session)
        if stats.get("error") == -1:
            return "Compaction unavailable (compactor not built)."
        # Persist compacted session
        await cm.save(session)
        saved = stats["saved_turns"]
        if saved == 0:
            return (
                f"Nothing to compact yet — history has {before} turns "
                f"(need more than {handler.compact_keep_recent})."
            )
        return (
            f"✅ Compacted: {stats['before']} turns → {stats['after']} turns "
            f"(saved {saved} turns; older content summarized into one block)."
        )

    async def on_auto_compact(sender_id: str, conversation_id: str, on: bool | None) -> str:
        scope = await cm.resolve_scope("telegram", sender_id, conversation_id)
        await handler._load_state(scope)
        s = handler.get_settings(scope)
        if on is None:
            return (
                f"Auto-compact is **{'on' if s.auto_compact else 'off'}**.\n"
                f"Threshold: {s.compact_threshold_tokens:,} tokens.\n"
                f"Use `/auto_compact on` or `/auto_compact off` to toggle."
            )
        await handler.set_auto_compact(scope, on)
        return (
            f"Auto-compact is now **{'on' if on else 'off'}**. "
            f"Triggers above {s.compact_threshold_tokens:,} tokens."
        )

    async def on_adaptive(sender_id: str, conversation_id: str, on: bool | None) -> str:
        scope = await cm.resolve_scope("telegram", sender_id, conversation_id)
        await handler._load_state(scope)
        s = handler.get_settings(scope)
        if on is None:
            tier_info = "  |  ".join(
                f"{k} → {v}" for k, v in handler.tier_models.items()
            )
            return (
                f"Adaptive routing is **{'on' if s.adaptive_routing else 'off'}**.\n"
                f"Tiers: {tier_info}\n"
                f"Use `/adaptive on` or `/adaptive off` to toggle."
            )
        await handler.set_adaptive_routing(scope, on)
        return (
            f"Adaptive routing is now **{'on' if on else 'off'}**. "
            + ("Each query auto-selects model tier." if on else "Using fixed model: " + s.model + ".")
        )

    async def on_last(sender_id: str, conversation_id: str) -> str:
        scope = await cm.resolve_scope("telegram", sender_id, conversation_id)
        await handler._load_state(scope)
        st = handler.get_stats(scope)
        if not st.last_model:
            return "No turns yet this session."

        lines = [
            "🔍 Last turn",
            f"  • model:           {st.last_model}",
            f"  • tokens in:       {st.last_input_tokens:,}  (measured)",
            f"  • tokens out:      {st.last_output_tokens:,}",
            f"  • cost:            ${st.last_cost_usd:.6f}",
        ]

        bd = st.last_breakdown
        if bd:
            est_total = bd.get("total_est", 0)
            lines.append(f"  • prompt breakdown (est, chars/4):")
            for key in ("system", "memory", "history", "profile", "steer", "user_msg"):
                val = bd.get(key, 0)
                if val > 0:
                    lines.append(f"      {key:10s} {val:>7,}")
            lines.append(f"      {'─' * 18}")
            lines.append(f"      {'subtotal':10s} {est_total:>7,}")
            # Delta = measured - estimated. Usually positive (tool schemas + framework overhead).
            if st.last_input_tokens > 0:
                delta = st.last_input_tokens - est_total
                lines.append(f"      {'tools+oh':10s} {delta:>7,} (measured − est)")

        return "\n".join(lines)

    async def on_streaming(sender_id: str, conversation_id: str, on: bool | None) -> str:
        scope = await cm.resolve_scope("telegram", sender_id, conversation_id)
        await handler._load_state(scope)
        s = handler.get_settings(scope)
        if on is None:
            return (
                f"Streaming is **{'on' if s.streaming else 'off'}**.\n"
                "When on, ReAct thoughts (💭 🔧 📋) appear in real-time before the answer.\n"
                "Use `/streaming on` or `/streaming off` to toggle."
            )
        await handler.set_streaming(scope, on)
        return (
            f"Streaming is now **{'on' if on else 'off'}**. "
            + ("ReAct thoughts will appear live." if on else "Silent mode (no thought display).")
        )

    async def on_task_status(sender_id: str, conversation_id: str) -> str:
        scope = await cm.resolve_scope("telegram", sender_id, conversation_id)
        if dispatcher is None:
            return "Dispatcher not wired — no task tracking available."

        if dispatcher.is_running(scope):
            state = dispatcher.get_state(scope)
            steer_pending = not state.steer_ctx.is_empty()
            lines = [
                "⚙️ Task running",
                f"  • task:          {state.task_summary or '(summarising…)'}",
                f"  • steer pending: {'yes — will apply at next step' if steer_pending else 'no'}",
            ]
        else:
            session = await cm.session_store.load_or_create(
                scope_key=scope, channel="telegram",
                sender_id=sender_id, conversation_id=conversation_id,
            )
            carry = session.extra.get("_carry_steer", [])
            lines = ["💤 Idle — no task running"]
            if carry:
                lines.append(f"  • carry steer:   {len(carry)} message(s) queued for next task")
                for s in carry:
                    lines.append(f"      · {s[:60]}")

        return "\n".join(lines)

    return {
        "on_clear": on_clear,
        "on_verbose": on_verbose,
        "on_model": on_model,
        "on_settings": on_settings,
        "on_status": on_status,
        "on_last": on_last,
        "on_task_status": on_task_status,
        "on_current_model": on_current_model,
        "on_adaptive": on_adaptive,
        "on_streaming": on_streaming,
        "on_compact": on_compact,
        "on_auto_compact": on_auto_compact,
    }


def _setup_logging() -> None:
    """Write INFO+ to stdout and DEBUG+ to ~/.ryuu/ryuu.log (rotating, 5 MB × 3)."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s — %(message)s")

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(fmt)

    fh = logging.handlers.RotatingFileHandler(
        LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    root.addHandler(sh)
    root.addHandler(fh)
    print(f"[ryuu-super] Logging to {LOG_PATH}")


async def run(use_telegram: bool) -> None:
    _setup_logging()

    if not os.getenv("OPENAI_API_KEY"):
        print(
            "[ryuu-super] ⚠️  OPENAI_API_KEY not set. "
            "Tools won't fire with the fake provider — set the key for the full demo.\n"
        )

    if DATABASE_URL:
        print(f"[ryuu-super] Storage:       Postgres ({DATABASE_URL.split('@')[-1]})")
    else:
        SUPER_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        print(f"[ryuu-super] SQLite store:  {SUPER_DB_PATH}")
        print(f"[ryuu-super] Memory dir:    {MEMORY_DIR}")

    # ── Layer 2 — single-tenant conversation manager ──────────────────
    # Postgres path: normalized session_turns table.
    # SQLite/fallback path: JSON blob via KVSessionStore.
    _ss = _session_store()
    cm = ConversationManager(
        session_store=_ss if _ss is not None else KVSessionStore(
            kv=_kv("sessions"),
            max_turns=20,
        ),
        scope_resolver=SingleTenantResolver(scope_key="owner"),
    )

    # ── Long-term memory ──────────────────────────────────────────────
    memory_backbone = MemoryBackbone(layers=[
        WorkingMemoryStore(
            collection=_coll("working"),
            max_entries=50,
        ),
        EpisodicMemoryStore(
            collection=_coll("episodic"),
            max_entries=500,
        ),
    ])

    # ── Layer 3 — generalist handler ──────────────────────────────────
    # Compaction needs ILLMProvider + PromptRegistry. If OPENAI_API_KEY
    # missing, compaction silently disabled (auto_compact + /compact no-op).
    compaction_provider = _build_compaction_provider()
    prompt_registry = make_framework_registry() if compaction_provider else None
    if compaction_provider:
        print("[ryuu-super] LLMCompactor enabled (provider + registry wired)")
    else:
        print("[ryuu-super] LLMCompactor disabled (no provider — compaction is no-op)")

    # ── ScopeDispatcher — per-scope concurrent message routing ────────
    # Reuses the OpenAI provider (gpt-4o-mini via dispatch/v3.yaml).
    # Without a provider, falls back to keyword heuristics only —
    # obvious STOP signals still caught; STEER/NEW edge cases → NEW.
    dispatch_logger = StandardDispatchLogger()
    dispatcher = ScopeDispatcher(
        classifier=MessageClassifier(provider=compaction_provider),
        provider=compaction_provider,
        logger=dispatch_logger,
    )
    if compaction_provider:
        print("[ryuu-super] ScopeDispatcher: LLM routing enabled (STOP / STEER / NEW)")
    else:
        print("[ryuu-super] ScopeDispatcher: heuristics-only (set OPENAI_API_KEY for LLM routing)")

    # Phase 9.0d.2 — Trust ReAct + tools. No preprocessing pipeline.
    # Agent's ReAct loop calls recall(query) when it decides. Handler
    # warm-starts with top-3 recent observations as baseline context.
    # (For non-agent / RAG / batch contexts, use ryuu_cognitive.recall.RecallPipeline.)
    print("[ryuu-super] ReAct paradigm: no recall preprocessing. LLM drives via tools.")

    # Phase 8.10 — Load MCP skills (filesystem, GitHub, etc.) from skills.yaml.
    # User edits ~/.ryuu/skills.yaml to add capabilities — OR (Phase 8.11)
    # the LLM installs them at runtime via install_skill / uninstall_skill.
    if SKILLS_PATH.exists():
        loader = MCPSkillsLoader.from_path(SKILLS_PATH)
        clients = loader.build_clients()
    else:
        clients = []
        print(f"[ryuu-super] No MCP skills config at {SKILLS_PATH} — starting with empty toolset")

    # Always construct the toolset (even if zero clients) so the LLM has a
    # live target to install_skill into via chat.
    mcp_toolset: MCPToolset = MCPToolset(clients=clients)
    await mcp_toolset.start_all()
    summary = mcp_toolset.server_summary()
    total = sum(summary.values())
    if total:
        print(f"[ryuu-super] MCP skills: {total} tools from {len(summary)} servers — {summary}")
    else:
        print(f"[ryuu-super] MCP skills: none active (use install_skill in chat to add)")

    # Phase 8.11 — Skill management tools. LLM can `list_available_skills` then
    # `install_skill('github', params={...})` without code edits or restart.
    # `from_layered` also merges ~/.ryuu/skill_registry.json (or $RYUU_SKILL_REGISTRY)
    # so users can curate their own skills installable via chat.
    skill_registry = SkillRegistry.from_layered()
    skill_manager = SkillManager(
        registry=skill_registry,
        toolset=mcp_toolset,
        yaml_path=SKILLS_PATH,
    )
    skill_toolset = SkillManagerToolset(manager=skill_manager)
    print(f"[ryuu-super] Skill registry: {len(skill_registry)} installable skills")

    # Phase 8.12 — Prompt Skills (Claude Code-style task templates).
    # User dir (wins) → bundled defaults. Hot-reload via mtime in handler.
    prompt_skill_registry = PromptSkillRegistry.from_dirs([
        PROMPT_SKILLS_USER_DIR,
        PROMPT_SKILLS_BUNDLED_DIR,
    ])
    prompt_skills_toolset = PromptSkillsToolset(registry=prompt_skill_registry)
    print(f"[ryuu-super] Prompt skills: {len(prompt_skill_registry)} loaded "
          f"({', '.join(prompt_skill_registry.names()) or 'none'})")

    from ryuu_system_tools import SystemToolset
    system_toolset = SystemToolset.from_layered()
    print(f"[ryuu-super] System tools: {len(system_toolset.tools)} loaded "
          f"({', '.join(system_toolset.tool_ids())})")

    _hss = _handler_state_store()
    _ps = _profile_store()
    handler = RyuuHandler(
        memory_backbone=memory_backbone,
        compaction_provider=compaction_provider,
        prompt_registry=prompt_registry,
        mcp_toolset=mcp_toolset,
        skill_toolset=skill_toolset,
        prompt_skills=prompt_skill_registry,
        prompt_skills_toolset=prompt_skills_toolset,
        system_toolset=system_toolset,
        warm_start_top_k=3,
        # Postgres path: normalized columns. SQLite path: JSON blob via IKVStore.
        state_store=_kv("handler_state") if _hss is None else None,
        normalized_state_store=_hss,
        profile_store=_ps,
    )

    # ── Orchestrator + channels ───────────────────────────────────────
    orch = ChannelOrchestrator(
        conversation_manager=cm,
        handler=handler,
        name="Ryuu Super",
        dispatcher=dispatcher,
        logger=dispatch_logger,
    )
    orch.register_channel(CLIAdapter())

    if use_telegram:
        from ryuu_messaging_telegram import TelegramAdapter

        owner_id = os.getenv("OWNER_TELEGRAM_ID", "").strip()
        if not owner_id:
            print(
                "[ryuu-super] ⚠️  OWNER_TELEGRAM_ID not set — bot will be PUBLIC.\n"
                "    To restrict, set: export OWNER_TELEGRAM_ID='your-numeric-id'\n"
                "    Get your ID from @userinfobot in Telegram.\n"
            )
            allowed: frozenset[str] | None = None
        else:
            allowed = frozenset({owner_id})
            print(f"[ryuu-super] Telegram allowed_senders = {{{owner_id}}} (single-tenant)")

        cbs = _build_telegram_callbacks(orch, handler, cm)

        async def stream_gateway(
            incoming: Any, chat_id: int, bot: Any
        ) -> Any:
            """Replace on_message for all regular messages.

            Non-streaming: delegates to orch._on_message() unchanged.
            Streaming: sends ⏳ placeholder, edits it with each thought/tool
            event, then returns the final OutgoingMessage for the adapter to send.
            """
            scope = await cm.resolve_scope(
                incoming.channel, incoming.sender_id, incoming.conversation_id
            )
            await handler._load_state(scope)
            s = handler.get_settings(scope)

            log = logging.getLogger("ryuu_sensei.stream_gateway")
            log.info(
                "stream_gateway: scope=%s streaming=%s adaptive=%s model=%s",
                scope, s.streaming, s.adaptive_routing, s.model,
            )

            # Dispatcher routing or streaming off → normal path
            if not s.streaming or (
                orch.dispatcher is not None and orch.dispatcher.is_running(scope)
            ):
                log.info("→ NORMAL path (streaming=%s, dispatcher_busy=%s)",
                         s.streaming,
                         orch.dispatcher is not None and orch.dispatcher.is_running(scope))
                return await orch._on_message(incoming)

            log.info("→ STREAMING path")

            # ── Streaming path ─────────────────────────────────────────
            placeholder = await bot.send_message(chat_id, "🤔 Đang xử lý…")
            log.info("placeholder sent: message_id=%s", placeholder.message_id)
            trace_lines: list[str] = []

            async def on_event(event_type: str, text: str) -> None:
                log.info("stream event: type=%s text=%r", event_type, text[:80])
                if event_type == "thought":
                    # Display ALL thoughts, including framework's generic
                    # "I'll use X to gather..." substitution — it's still a
                    # signal that LLM is using a tool. Without it, tool-use
                    # turns would silently jump from placeholder to tool_call.
                    trace_lines.append(f"💭 {text.strip()[:300]}")
                elif event_type == "tool_call":
                    trace_lines.append(f"🔧 {text}")
                elif event_type == "tool_result":
                    preview = text[:200] + "…" if len(text) > 200 else text
                    trace_lines.append(f"📋 {preview}")
                elif event_type == "final":
                    return

                body = "\n".join(trace_lines) if trace_lines else "🤔 Đang xử lý…"
                try:
                    await bot.edit_message_text(
                        text=body,
                        chat_id=chat_id,
                        message_id=placeholder.message_id,
                    )
                    log.info("edit OK (%d chars, %d lines)", len(body), len(trace_lines))
                except Exception as exc:  # noqa: BLE001
                    log.warning("edit_message_text FAILED: %s: %s",
                                type(exc).__name__, exc)

            session = await cm.get_session(incoming)
            outgoing = await handler.handle(incoming, session, on_event=on_event)
            session.extra.pop("_dispatcher_state", None)
            await cm.save(session)

            # If no thoughts were emitted (direct answer), remove the ⏳ placeholder
            # so it doesn't sit as a stray message above the reply.
            if not trace_lines:
                try:
                    await bot.delete_message(chat_id, placeholder.message_id)
                except Exception:  # noqa: BLE001
                    pass
            return outgoing

        tg = TelegramAdapter(
            bot_token=os.getenv("RYUU_BOT_TOKEN", os.getenv("TELEGRAM_BOT_TOKEN", "")),
            on_clear=cbs["on_clear"],
            on_verbose=cbs["on_verbose"],
            on_model=cbs["on_model"],
            on_settings=cbs["on_settings"],
            on_status=cbs["on_status"],
            on_task_status=cbs["on_task_status"],
            on_current_model=cbs["on_current_model"],
            on_compact=cbs["on_compact"],
            on_auto_compact=cbs["on_auto_compact"],
            on_adaptive=cbs["on_adaptive"],
            on_streaming=cbs["on_streaming"],
            on_last=cbs["on_last"],
            stream_gateway=stream_gateway,
            bot_commands=BOT_COMMANDS,
            allowed_models=ALLOWED_MODELS,
            allowed_senders=allowed,
            welcome_text=(
                "Konnichiwa! I am Ryuu Sensei (流先生) — your private assistant.\n\n"
                "I remember things you tell me across sessions. Try:\n"
                "  • 'My name is Phuong and I'm building UAAF'\n"
                "  • Restart me — then ask 'What do you know about me?'\n\n"
                "Commands: /help  /status  /clear  /verbose on"
            ),
        )
        orch.register_channel(tg)

    try:
        await orch.start()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await orch.stop()
        await mcp_toolset.stop_all()


def main() -> int:
    parser = argparse.ArgumentParser(description="Ryuu Sensei SuperBot")
    parser.add_argument(
        "--telegram",
        action="store_true",
        help="Also start Telegram adapter (requires RYUU_BOT_TOKEN + OWNER_TELEGRAM_ID)",
    )
    args = parser.parse_args()
    try:
        asyncio.run(run(use_telegram=args.telegram))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
