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
from ryuu_storage_jsonl import JsonlCollectionStore
from ryuu_storage_sqlite import SqliteKVStore

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
        s = await handler.set_model(scope, model)
        return f"Model switched to **{s.model}**."

    async def on_settings(sender_id: str, conversation_id: str) -> str:
        scope = await cm.resolve_scope("telegram", sender_id, conversation_id)
        await handler._load_state(scope)
        s = handler.get_settings(scope)
        return (
            "⚙️ Settings\n"
            f"  • model:   {s.model}\n"
            f"  • verbose: {'on' if s.verbose else 'off'}\n\n"
            f"Allowed models: {', '.join(ALLOWED_MODELS)}\n"
            "Change via /model (tap to switch) or /verbose on|off"
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
        return (
            "📊 Session status\n"
            f"  • model:           {s.model}\n"
            f"  • verbose:         {'on' if s.verbose else 'off'}\n"
            f"  • context buffer:  {len(session.history)} / {session.max_turns} turns\n"
            f"  • LLM calls:       {stats.turns}\n"
            f"  • tokens in/out:   {stats.input_tokens:,} / {stats.output_tokens:,}\n"
            f"  • cost so far:     ${stats.total_usd:.6f}"
        )

    async def on_current_model(sender_id: str, conversation_id: str) -> str:
        scope = await cm.resolve_scope("telegram", sender_id, conversation_id)
        await handler._load_state(scope)
        return handler.get_settings(scope).model

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

    return {
        "on_clear": on_clear,
        "on_verbose": on_verbose,
        "on_model": on_model,
        "on_settings": on_settings,
        "on_status": on_status,
        "on_current_model": on_current_model,
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

    SUPER_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[ryuu-super] SQLite store:  {SUPER_DB_PATH}")
    print(f"[ryuu-super] Memory dir:    {MEMORY_DIR}")

    # ── Layer 2 — single-tenant conversation manager ──────────────────
    cm = ConversationManager(
        session_store=KVSessionStore(
            kv=SqliteKVStore(db_path=SUPER_DB_PATH, table="sessions"),
            max_turns=20,
        ),
        scope_resolver=SingleTenantResolver(scope_key="owner"),
    )

    # ── Long-term memory: JSONL per-scope files (OpenClaw pattern) ────
    memory_backbone = MemoryBackbone(layers=[
        WorkingMemoryStore(
            collection=JsonlCollectionStore(root_dir=MEMORY_DIR, table="working"),
            max_entries=50,
        ),
        EpisodicMemoryStore(
            collection=JsonlCollectionStore(root_dir=MEMORY_DIR, table="episodic"),
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
        state_store=SqliteKVStore(db_path=SUPER_DB_PATH, table="handler_state"),
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
        tg = TelegramAdapter(
            bot_token=os.getenv("RYUU_BOT_TOKEN", os.getenv("TELEGRAM_BOT_TOKEN", "")),
            on_clear=cbs["on_clear"],
            on_verbose=cbs["on_verbose"],
            on_model=cbs["on_model"],
            on_settings=cbs["on_settings"],
            on_status=cbs["on_status"],
            on_current_model=cbs["on_current_model"],
            on_compact=cbs["on_compact"],
            on_auto_compact=cbs["on_auto_compact"],
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
