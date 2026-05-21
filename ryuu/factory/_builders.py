"""Construction helpers for Agent factory.

Module-level functions taking Agent instance (or specific fields). Build
ToolRegistry, HookRegistry, cross-cutting concerns, and wrap registry with
PRE/POST_TOOL hook firing. Extracted from agent.py for file size + isolation.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from ryuu_execution.tool_registry import ITool, ToolRegistry
from ryuu_workflow.context import ContextScope

from ryuu._tool_introspect import build_tool_schema
from ryuu.hooks import (
    HookEvent,
    HookRegistry,
    PostToolContext,
    PreToolContext,
)

if TYPE_CHECKING:
    from ryuu.factory.agent import Agent


def build_tool_registry(agent: "Agent") -> ToolRegistry:
    """Build registry from one of: Mode C (passed), Mode A/B (list), or empty.

    Mode D (YAML tool schemas) is layered on top in `apply_yaml_tool_schemas`.
    """
    # Mode C: user provided pre-built registry — use directly
    if agent.tool_registry is not None:
        registry = agent.tool_registry
    else:
        registry = ToolRegistry()
        # Mode A (callable) + Mode B (ITool) heterogeneous list
        for item in agent.tools:
            if isinstance(item, ITool):
                # Mode B: ITool instance — register as-is (schema already attached)
                registry.register(item.tool_id, item)
            else:
                # Mode A: callable — wrap + auto-introspect schema
                schema = build_tool_schema(item)
                registry.register(item.__name__, item)
                handler = registry._handlers[item.__name__]
                handler.schema = schema   # type: ignore[attr-defined]

    # Mode D: if Mode 4 (YAML prompt) active, attach YAML schemas by name
    apply_yaml_tool_schemas(agent, registry)
    return registry


def apply_yaml_tool_schemas(agent: "Agent", registry: ToolRegistry) -> None:
    """Mode D: attach YAML tool schemas to existing registry handlers.

    Behavior:
      - Mode 4 active + user opted into tools (via `tools=` OR `tool_registry=`)
        → strict pairing: every YAML tool must have a handler, else ValueError.
      - Mode 4 active + user did NOT pass tools/registry → silently skip YAML
        tools (user signals "prompts only").
    """
    if agent.prompt is None or agent._yaml_tools_cache is None:
        return
    # User opted out: no tool_registry, no tools list → ignore YAML tools
    if agent.tool_registry is None and not agent.tools:
        return

    from ryuu.prompts.models import ToolDefinition

    for tool_def in agent._yaml_tools_cache:
        assert isinstance(tool_def, ToolDefinition)
        handler = registry._handlers.get(tool_def.name)
        if handler is None:
            raise ValueError(
                f"YAML defines tool {tool_def.name!r} but no handler registered. "
                f"Add `{tool_def.name}` to your ToolRegistry or remove from YAML."
            )
        handler.schema = tool_def.to_openai_schema()   # type: ignore[attr-defined]


def build_hook_registry(agent: "Agent") -> HookRegistry | None:
    """Build HookRegistry from `hooks={"event": [handlers]}` dict.

    Returns None if hooks is empty/missing — internal agent skips firing
    when registry is None for zero overhead.
    """
    if not agent.hooks:
        return None
    registry = HookRegistry()
    registry.register_dict(agent.hooks)   # type: ignore[arg-type]
    return registry


def wrap_tool_registry_with_hooks(
    tool_registry: ToolRegistry,
    hook_registry: HookRegistry | None,
    scope: ContextScope | None = None,
) -> None:
    """Phase 9.2: wrap each handler in ToolRegistry to fire PRE_TOOL/POST_TOOL.

    Mutation: PRE_TOOL handler can replace `args` via `ctx.replace(args=...)`.
    Block: PRE_TOOL handler can raise to abort tool call.
    """
    if hook_registry is None:
        return
    if not (hook_registry.has_handlers(HookEvent.PRE_TOOL)
            or hook_registry.has_handlers(HookEvent.POST_TOOL)):
        return

    for name, handler in list(tool_registry._handlers.items()):
        original_execute = handler.execute

        async def wrapped(args: dict[str, Any], _name: str = name,
                          _orig: Any = original_execute) -> Any:
            # Fire PRE_TOOL
            pre_ctx = PreToolContext(
                event=HookEvent.PRE_TOOL,
                correlation_id="",
                scope=scope or ContextScope(user_id="", session_id="", domain=""),
                tool_name=_name,
                args=args,
            )
            result_ctx = await hook_registry.fire(HookEvent.PRE_TOOL, pre_ctx)
            args = result_ctx.args if isinstance(result_ctx, PreToolContext) else args

            # Execute real handler
            result = await _orig(args)

            # Fire POST_TOOL
            post_ctx = PostToolContext(
                event=HookEvent.POST_TOOL,
                correlation_id="",
                scope=scope or ContextScope(user_id="", session_id="", domain=""),
                tool_name=_name,
                args=args,
                result=result,
            )
            await hook_registry.fire(HookEvent.POST_TOOL, post_ctx)
            return result

        handler.execute = wrapped   # type: ignore[method-assign]


def build_cross_cutting(agent: "Agent") -> tuple[Any, Any, Any, Any]:
    """Build (cost_tracker, rate_limiter, audit_logger, tracer) from agent flags.

    None/False kwargs → NullObject (zero overhead). True/set → Real impl.
    Returns tuple in that order for unpacking.
    """
    from ryuu_core.nulls import (
        NullAuditLogger,
        NullCostTracker,
        NullRateLimiter,
        NullTracer,
    )

    cost: Any = NullCostTracker()
    if agent.budget_usd is not None:
        from ryuu_observability.cost import CostPolicy, CostTracker

        # `budget_usd` maps to per-user-per-day cap (closest semantic for
        # a session budget — CostPolicy doesn't have a per-session field).
        cost = CostTracker(CostPolicy(per_user_per_day_usd=agent.budget_usd))

    rate: Any = NullRateLimiter()
    if agent.rate_limit_rps is not None:
        from ryuu_observability.rate_limit import RateLimiter, RatePolicy

        rate = RateLimiter(RatePolicy(rps=agent.rate_limit_rps))

    audit: Any = NullAuditLogger()
    if agent.audit:
        from ryuu_observability.audit import AuditConfig, AuditLogger

        # Phase 9.3: default to queued_file (non-blocking append).
        # Trade-off: events may lose ~100ms on hard crash. For strict
        # compliance use backend="file" via AuditLogger directly.
        config = AuditConfig(
            backend="queued_file",
            file_path=str(Path("./ryuu_audit.jsonl")),
        )
        audit = AuditLogger(config=config)

    tracer: Any = NullTracer()
    if agent.trace:
        from ryuu_observability.tracer import Tracer

        tracer = Tracer()

    return cost, rate, audit, tracer
