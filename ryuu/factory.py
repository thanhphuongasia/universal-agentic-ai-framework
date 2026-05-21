"""Factory `Agent()` — lean single-agent + tool-calling facade.

Phase 10 MVP: Mode 1 (`instructions=str`) + Mode A (callable list `tools=[...]`).
Phase 10.1 adds Mode 2: `system=str`, `user_template=str`, `examples=[...]`.

For advanced use cases (multi-step domain logic, custom strategies), use class-based
`BaseAgent` subclass — Factory does NOT replace it.

See: docs/guides/quickstart.md §1, tasks/plan-phase10-factory.md
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import anyio

from ryuu_core.models import AgentResult, Cost, Task
from ryuu_execution.agent import BaseAgent
from ryuu_execution.llm_agent import (
    LLMAgent,
    PrintCallbacks,
    ReActCallbacks,
    SilentCallbacks,
)
from ryuu_execution.tool_registry import ITool, ToolRegistry
from ryuu_providers.llm import CompletionRequest, ILLMProvider, Message
from ryuu_workflow.context import ContextScope, ExecutionContext

from ryuu._provider_detect import build_provider
from ryuu._tool_introspect import build_tool_schema
from ryuu.hooks import (
    HookContext,
    HookEvent,
    HookRegistry,
    OnBudgetExceededContext,
    OnCompleteContext,
    OnErrorContext,
    OnRateLimitedContext,
    PostExecuteContext,
    PostLLMContext,
    PostToolContext,
    PreExecuteContext,
    PreLLMContext,
    PreToolContext,
)
from ryuu.prompts.registry import PromptRegistry

__all__ = ["Agent", "StreamEvent"]


@dataclass
class StreamEvent:
    """Event yielded by `Agent.stream()`. Phase 10.4.

    Types:
      token        — token-by-token LLM output (currently aggregated; per-token in 10.5)
      thought      — ReAct reasoning text between tool calls
      tool_call    — before tool invocation (tool_name + args)
      tool_result  — after tool returns (tool_name + result)
      error        — exception in lifecycle
      final        — done, has final answer text
    """

    type: Literal["token", "thought", "tool_call", "tool_result", "error", "final"]
    text: str = ""
    tool_name: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    result: Any = None
    error: Exception | None = None


# `.run(**kwargs)` reserves these keys for ContextScope; remaining kwargs are
# treated as template variables for `user_template` substitution.
RESERVED_SCOPE_KEYS: frozenset[str] = frozenset(
    {"user_id", "session_id", "domain", "correlation_id"}
)


# ---------------------------------------------------------------------------
# Internal LLMAgent subclass — concrete _execute() for Factory
# ---------------------------------------------------------------------------


@dataclass
class _FactoryLLMAgent(LLMAgent):
    """Concrete LLMAgent owned by Factory.

    Holds Factory-specific config (system_prompt, examples, max_tokens,
    temperature, max_iterations) that flow into CompletionRequest + ReAct loop.
    """

    system_prompt: str = ""
    examples: list[dict[str, str]] | None = None
    _max_tokens: int | None = None
    _temperature: float = 0.7
    _max_iterations: int = 5
    _model_name: str = ""
    _verbose: bool = False
    _budget_tokens: int | None = None
    _fallback_providers: list[ILLMProvider] = field(default_factory=list)
    _hook_registry: HookRegistry | None = None

    async def _execute(self, task: Task, context: ExecutionContext) -> AgentResult:
        # ── Fire PRE_EXECUTE ──
        if self._hook_registry is not None:
            pre_ctx = PreExecuteContext(
                event=HookEvent.PRE_EXECUTE,
                correlation_id=context.correlation_id,
                scope=context.scope,
                task=task,
            )
            await self._hook_registry.fire(HookEvent.PRE_EXECUTE, pre_ctx)

        try:
            result = await self._run_inner(task, context)
        except Exception as exc:
            if self._hook_registry is not None:
                # Phase 9.2: specialized events for budget/rate before generic on_error
                from ryuu_core.errors import BudgetExceededError, RateLimitTimeout

                if isinstance(exc, BudgetExceededError):
                    budget_ctx = OnBudgetExceededContext(
                        event=HookEvent.ON_BUDGET_EXCEEDED,
                        correlation_id=context.correlation_id,
                        scope=context.scope,
                        error=exc,
                        task=task,
                    )
                    await self._hook_registry.fire(HookEvent.ON_BUDGET_EXCEEDED, budget_ctx)
                elif isinstance(exc, RateLimitTimeout):
                    rate_ctx = OnRateLimitedContext(
                        event=HookEvent.ON_RATE_LIMITED,
                        correlation_id=context.correlation_id,
                        scope=context.scope,
                        error=exc,
                        task=task,
                    )
                    await self._hook_registry.fire(HookEvent.ON_RATE_LIMITED, rate_ctx)

                # Generic on_error fires for ALL exceptions (always)
                err_ctx = OnErrorContext(
                    event=HookEvent.ON_ERROR,
                    correlation_id=context.correlation_id,
                    scope=context.scope,
                    error=exc,
                    task=task,
                )
                await self._hook_registry.fire(HookEvent.ON_ERROR, err_ctx)
            raise

        # ── Fire POST_EXECUTE + ON_COMPLETE ──
        if self._hook_registry is not None:
            post_ctx = PostExecuteContext(
                event=HookEvent.POST_EXECUTE,
                correlation_id=context.correlation_id,
                scope=context.scope,
                task=task,
                result=result,
            )
            await self._hook_registry.fire(HookEvent.POST_EXECUTE, post_ctx)

            complete_ctx = OnCompleteContext(
                event=HookEvent.ON_COMPLETE,
                correlation_id=context.correlation_id,
                scope=context.scope,
                result=result,
            )
            await self._hook_registry.fire(HookEvent.ON_COMPLETE, complete_ctx)

        return result

    async def _react_loop_with_failover(self, request, *, domain: str):
        """Phase 10.6: try primary LLM, on Exception try each fallback provider.

        Resets `self.llm` to primary at the end so subsequent calls always start
        with the preferred provider (it may have recovered).
        """
        providers = [self.llm, *self._fallback_providers]
        last_exc: Exception | None = None
        primary = self.llm

        for prov in providers:
            try:
                self.llm = prov
                return await self._react_loop(
                    request, max_rounds=self._max_iterations, domain=domain
                )
            except Exception as exc:
                last_exc = exc
                continue
            finally:
                self.llm = primary

        # All providers failed
        assert last_exc is not None
        raise last_exc

    async def _run_inner(self, task: Task, context: ExecutionContext) -> AgentResult:
        """Real LLM execution — extracted so _execute can wrap with hook firing."""
        # Factory pre-fills `user_content`; fall back to `query` for legacy callers.
        user_content = str(task.payload.get("user_content") or task.payload.get("query", ""))

        messages: list[Message] = []
        if self.system_prompt:
            messages.append(Message(role="system", content=self.system_prompt))

        # Few-shot examples interleave as alternating user/assistant pairs
        # BEFORE the real user query — OpenAI convention.
        if self.examples:
            for ex in self.examples:
                messages.append(Message(role="user", content=ex["user"]))
                messages.append(Message(role="assistant", content=ex["assistant"]))

        messages.append(Message(role="user", content=user_content))

        # ── Fire PRE_LLM ──
        if self._hook_registry is not None:
            pre_llm_ctx = PreLLMContext(
                event=HookEvent.PRE_LLM,
                correlation_id=context.correlation_id,
                scope=context.scope,
                messages=messages,
                model=self._model_name,
            )
            await self._hook_registry.fire(HookEvent.PRE_LLM, pre_llm_ctx)
            messages = pre_llm_ctx.messages   # accept mutations

        # Build tool schema list if registry has any handlers
        tools_payload: list[dict[str, Any]] | None = None
        if self.tool_registry and self.tool_registry._handlers:
            tools_payload = [
                handler.schema
                for handler in self.tool_registry._handlers.values()
                if getattr(handler, "schema", None) is not None
            ] or None

        request = CompletionRequest(
            messages=messages,
            model=self._model_name,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            tools=tools_payload,
        )

        # Phase 10.6 failover: try primary, then each fallback in order.
        output, usage = await self._react_loop_with_failover(
            request, domain=context.scope.domain
        )

        # ── Fire POST_LLM ──
        if self._hook_registry is not None:
            post_llm_ctx = PostLLMContext(
                event=HookEvent.POST_LLM,
                correlation_id=context.correlation_id,
                scope=context.scope,
                response=output,
                model=self._model_name,
            )
            await self._hook_registry.fire(HookEvent.POST_LLM, post_llm_ctx)

        cost = Cost(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            usd=0.0,  # Pricing lookup deferred — _react_loop doesn't track $ yet
            provider=self.llm.__class__.__name__.replace("Provider", "").lower(),
            model=self._model_name,
        )
        return AgentResult(task_id=task.task_id, output=output, cost=cost)


# ---------------------------------------------------------------------------
# Public Agent factory
# ---------------------------------------------------------------------------


@dataclass
class Agent:
    """Lean factory for single-agent + tool-calling use cases.

    Example::

        from ryuu import Agent

        agent = Agent(model="gpt-4o-mini", instructions="You are a helper")
        result = await agent.run("What is Python?")

    See quickstart §1 for full API reference.
    """

    # Required — str or list (Phase 10.4 multi-provider fallback chain)
    model: str | list[str]

    # Prompt — Mode 1 (MVP, shorthand)
    instructions: str = ""

    # Prompt — Mode 2 (Phase 10.1): explicit system + user_template + few-shot examples
    # Phase 10.2: `system` and `user_template` may also be Path to a file —
    # contents are read at __post_init__ and stored as str.
    system: str | Path | None = None
    user_template: str | Path | None = None
    examples: list[dict[str, str]] | None = None

    # Prompt — Mode 4 (Phase 10.2): YAML registry reference "project:version:name"
    # Loads system + user_template from versioned YAML. Mutually exclusive with
    # Mode 1/2 fields (instructions / system / user_template / examples).
    # Tools still passed via Mode A (callable list) — Mode D (YAML tool integration)
    # deferred to Phase 10.3.
    prompt: str | None = None
    prompt_registry: PromptRegistry | None = None

    # Tools — Mode A (MVP, callable) + Mode B (Phase 10.3, ITool instances).
    # List may mix callables and ITool objects.
    tools: list[Any] = field(default_factory=list)

    # Tools — Mode C (Phase 10.3): pre-built ToolRegistry (DI + allowed_domains).
    # Mutually exclusive with `tools=` Mode A/B.
    tool_registry: ToolRegistry | None = None

    # Per-call LLM limits
    max_tokens: int | None = None
    temperature: float = 0.7

    # Per-run ReAct loop limit
    max_iterations: int = 5

    # Per-session cost cap (None = NullObject)
    budget_usd: float | None = None

    # Per-session token cap (Phase 10.4 — alt/complement to budget_usd)
    budget_tokens: int | None = None

    # Cross-cutting toggles (None/False = NullObject)
    rate_limit_rps: float | None = None
    audit: bool = False
    trace: bool = False
    verbose: bool = False

    # Provider override (optional — default: env var auto-detect)
    api_key: str | None = None

    # Hooks — Phase 9 dynamic lifecycle injection.
    # dict mapping event name → list of handlers, e.g.
    #   hooks={"pre_execute": [my_hook], "on_error": [error_logger]}
    hooks: dict[str, list[Callable[..., Any]]] | None = None

    # Internal — built lazily, exposed for tests
    _agent: _FactoryLLMAgent = field(init=False, repr=False)
    # Mode D: cache of YAML tool defs (populated by _resolve_yaml_prompt)
    _yaml_tools_cache: list[Any] | None = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        # Mode 3: resolve Path → file contents before validation so downstream
        # logic only ever sees str | None.
        self._resolve_file_paths()
        # Mode 4: load from YAML registry — sets system + user_template before
        # _validate() so the resolved fields are subject to the same checks.
        self._resolve_yaml_prompt()
        self._validate()

        # Multi-provider fallback: model=list → primary + fallback chain
        if isinstance(self.model, list):
            primary_model = self.model[0]
            fallback_models = self.model[1:]
        else:
            primary_model = self.model
            fallback_models = []

        provider = build_provider(primary_model, api_key=self.api_key)
        fallback_providers = [
            build_provider(m, api_key=self.api_key) for m in fallback_models
        ]
        tool_registry = self._build_tool_registry()
        hook_registry = self._build_hook_registry()
        # Phase 9.2: install PRE_TOOL/POST_TOOL wrappers on tool handlers
        self._wrap_tool_registry_with_hooks(tool_registry, hook_registry)
        cost, rate, audit, tracer = self._build_cross_cutting()

        # Strip optional provider prefix from model name for CompletionRequest
        model_name = primary_model.split(":", 1)[1] if ":" in primary_model else primary_model

        callbacks: ReActCallbacks = PrintCallbacks() if self.verbose else SilentCallbacks()

        # System prompt: Mode 2 `system` takes precedence over Mode 1 `instructions`
        # (validation in _validate prevents both being set simultaneously).
        resolved_system = self.system if self.system is not None else self.instructions

        self._agent = _FactoryLLMAgent(
            agent_id=f"factory-{id(self)}",
            llm=provider,
            tool_registry=tool_registry,
            callbacks=callbacks,
            cost_tracker=cost,
            rate_limiter=rate,
            audit_logger=audit,
            tracer=tracer,
            system_prompt=resolved_system,
            examples=self.examples,
            _max_tokens=self.max_tokens,
            _temperature=self.temperature,
            _max_iterations=self.max_iterations,
            _model_name=model_name,
            _verbose=self.verbose,
            _budget_tokens=self.budget_tokens,
            _fallback_providers=fallback_providers,
            _hook_registry=hook_registry,
        )

    async def _stream_tokens(
        self, message: str | None = None, **kwargs: Any
    ) -> AsyncIterator[StreamEvent]:
        """Phase 10.6: token-by-token streaming via provider.stream() (no tools).

        Yields `token` events for each chunk + final `final` event with full text.
        """
        # Resolve user content (same logic as .run)
        scope_kwargs = {k: kwargs.pop(k) for k in list(kwargs) if k in RESERVED_SCOPE_KEYS}
        if self.user_template is not None:
            user_content = self.user_template.format(**kwargs)
        elif message is not None:
            user_content = message
        else:
            raise ValueError("Pass `message` or set `user_template=`")
        del scope_kwargs  # not used in stream path (no Task)

        messages: list[Message] = []
        if self.system_prompt_resolved():
            messages.append(Message(role="system", content=self.system_prompt_resolved()))
        if self.examples:
            for ex in self.examples:
                messages.append(Message(role="user", content=ex["user"]))
                messages.append(Message(role="assistant", content=ex["assistant"]))
        messages.append(Message(role="user", content=user_content))

        model_name = (
            self.model[0].split(":", 1)[-1] if isinstance(self.model, list)
            else self.model.split(":", 1)[-1] if ":" in self.model
            else self.model
        )
        request = CompletionRequest(
            messages=messages, model=model_name,
            temperature=self.temperature, max_tokens=self.max_tokens, tools=None,
        )

        full_text_parts: list[str] = []
        async for chunk in self._agent.llm.stream(request):
            if chunk.content:
                full_text_parts.append(chunk.content)
                yield StreamEvent(type="token", text=chunk.content)
        yield StreamEvent(type="final", text="".join(full_text_parts))

    def system_prompt_resolved(self) -> str:
        """Resolve system prompt: Mode 2 system takes precedence over Mode 1 instructions."""
        return self.system if isinstance(self.system, str) else (self.instructions or "")

    async def stream(self, message: str | None = None, **kwargs: Any) -> AsyncIterator[StreamEvent]:
        """Async generator yielding StreamEvent during lifecycle.

        Yields events: token / thought / tool_call / tool_result / error / final.

        Two modes:
          - **No tools** (Phase 10.6): uses provider.stream() for token-by-token
            output. Yields one or more `token` events plus final `final` event.
          - **With tools** (Phase 10.4): uses ReAct loop callbacks. Yields semantic
            events (thought / tool_call / tool_result / final). Per-token emission
            during ReAct is deferred (multi-call coordination).

        Bridge LLMAgent.callbacks → anyio memory stream. The agent runs in a
        background task; this generator pulls events from the queue until the
        agent finishes (or errors).
        """
        # Phase 10.6: token streaming for no-tool case via provider.stream() directly
        if not self.tools and self.tool_registry is None:
            async for ev in self._stream_tokens(message, **kwargs):
                yield ev
            return
        send_stream, receive_stream = anyio.create_memory_object_stream[StreamEvent](
            max_buffer_size=64
        )

        class _StreamCallbacks:
            async def on_thought(self, text: str) -> None:
                await send_stream.send(StreamEvent(type="thought", text=text))

            async def on_action(self, tool_name: str, args: dict[str, Any]) -> None:
                await send_stream.send(
                    StreamEvent(type="tool_call", tool_name=tool_name, args=args)
                )

            async def on_observation(self, tool_name: str, result: str) -> None:
                await send_stream.send(
                    StreamEvent(type="tool_result", tool_name=tool_name, result=result)
                )

            async def on_final(self, text: str) -> None:
                await send_stream.send(StreamEvent(type="final", text=text))

        # Resolve user content (same logic as .run)
        scope_kwargs = {k: kwargs.pop(k) for k in list(kwargs) if k in RESERVED_SCOPE_KEYS}
        template_vars = kwargs
        if self.user_template is not None:
            user_content = self.user_template.format(**template_vars)
        elif message is not None:
            user_content = message
        else:
            raise ValueError(
                "Pass `message` positional (Mode 1) OR set `user_template=` "
                "+ pass template vars as kwargs (Mode 2)."
            )

        scope = ContextScope(
            user_id=scope_kwargs.get("user_id", "anonymous"),
            session_id=scope_kwargs.get("session_id", str(uuid.uuid4())),
            domain=scope_kwargs.get("domain", "default"),
        )
        ctx = ExecutionContext(
            scope=scope,
            correlation_id=scope_kwargs.get("correlation_id") or str(uuid.uuid4()),
        )
        task = Task(task_id=str(uuid.uuid4()), payload={"user_content": user_content})

        # Swap callbacks for streaming, restore after
        original_callbacks = self._agent.callbacks
        self._agent.callbacks = _StreamCallbacks()  # type: ignore[assignment]

        async def _runner() -> None:
            try:
                await self._agent.execute(task, ctx)
            except Exception as exc:
                await send_stream.send(StreamEvent(type="error", error=exc))
            finally:
                await send_stream.aclose()

        try:
            async with anyio.create_task_group() as tg:
                tg.start_soon(_runner)
                async for event in receive_stream:
                    yield event
        finally:
            self._agent.callbacks = original_callbacks

    async def run(self, message: str | None = None, **kwargs: Any) -> AgentResult:
        """Execute agent. Behavior depends on prompt mode.

        Mode 1 (instructions): pass `message` positional.
            await agent.run("What is Python?")

        Mode 2 (user_template): pass template vars as kwargs.
            await agent.run(text="Hello", lang="VN")  # fills {text}, {lang}

        Reserved kwargs go to ContextScope (NOT template substitution):
            user_id, session_id, domain, correlation_id

        Scope defaults: user_id="anonymous", session_id=uuid, domain="default".
        """
        # Split kwargs: reserved scope keys vs template variables
        scope_kwargs = {k: kwargs.pop(k) for k in list(kwargs) if k in RESERVED_SCOPE_KEYS}
        template_vars = kwargs

        # Resolve user content
        if self.user_template is not None:
            user_content = self.user_template.format(**template_vars)
        elif message is not None:
            user_content = message
        else:
            raise ValueError(
                "Pass `message` positional (Mode 1) OR set `user_template=` "
                "+ pass template vars as kwargs (Mode 2)."
            )

        scope = ContextScope(
            user_id=scope_kwargs.get("user_id", "anonymous"),
            session_id=scope_kwargs.get("session_id", str(uuid.uuid4())),
            domain=scope_kwargs.get("domain", "default"),
        )
        correlation_id = scope_kwargs.get("correlation_id") or str(uuid.uuid4())
        ctx = ExecutionContext(scope=scope, correlation_id=correlation_id)
        task = Task(task_id=str(uuid.uuid4()), payload={"user_content": user_content})
        return await self._agent.execute(task, ctx)

    # ── Private builders ─────────────────────────────────────────────────

    def _resolve_yaml_prompt(self) -> None:
        """Mode 4: load `system` + `user_template` from YAML registry reference.

        Format: `prompt="project:version:name"`. Mutually exclusive with Mode 1/2
        fields (`instructions`, `system`, `user_template`, `examples`).
        """
        if self.prompt is None:
            return

        # Mutual exclusion check BEFORE loading (so user error surfaces cleanly).
        for field_name, value in (
            ("instructions", self.instructions),
            ("system", self.system),
            ("user_template", self.user_template),
            ("examples", self.examples),
        ):
            if value:
                raise ValueError(
                    f"Cannot mix `prompt=` (Mode 4 YAML reference) with `{field_name}=`. "
                    f"YAML provides system + user_template — remove `{field_name}` "
                    f"or switch to Mode 1/2."
                )

        # Parse "project:version:name"
        parts = self.prompt.split(":")
        if len(parts) != 3:
            raise ValueError(
                f"prompt reference must be 'project:version:name', got: {self.prompt!r}"
            )
        project, version, name = parts

        # Resolve registry — explicit > auto-detect ./prompts/
        registry = self.prompt_registry
        if registry is None:
            default_root = Path("./prompts")
            if not default_root.exists():
                raise ValueError(
                    f"No `prompt_registry=` provided and ./prompts/ does not exist. "
                    f"Either pass PromptRegistry(prompts_root=...) or create ./prompts/."
                )
            registry = PromptRegistry(prompts_root=default_root)

        # Load + extract
        cfg = registry.load(project, version)
        template = cfg.get_prompt(name)   # raises KeyError if name missing
        self.system = template.system
        self.user_template = template.user
        # Cache YAML tool defs for Mode D pairing in _apply_yaml_tool_schemas
        self._yaml_tools_cache = list(cfg.tools) if cfg.tools else None

    def _resolve_file_paths(self) -> None:
        """Mode 3: if `system` or `user_template` is a Path, read file → str."""
        if isinstance(self.system, Path):
            if not self.system.exists():
                raise FileNotFoundError(
                    f"system prompt file not found: {self.system}"
                )
            self.system = self.system.read_text()
        if isinstance(self.user_template, Path):
            if not self.user_template.exists():
                raise FileNotFoundError(
                    f"user_template file not found: {self.user_template}"
                )
            self.user_template = self.user_template.read_text()

    def _validate(self) -> None:
        if not self.model:
            raise ValueError("model is required (non-empty string or list)")
        if isinstance(self.model, list) and len(self.model) == 0:
            raise ValueError("model list cannot be empty")
        if self.budget_usd is not None and self.budget_usd <= 0:
            raise ValueError(f"budget_usd must be positive, got {self.budget_usd}")
        if self.budget_tokens is not None and self.budget_tokens <= 0:
            raise ValueError(f"budget_tokens must be positive, got {self.budget_tokens}")
        if self.rate_limit_rps is not None and self.rate_limit_rps <= 0:
            raise ValueError(f"rate_limit_rps must be positive, got {self.rate_limit_rps}")
        if self.max_tokens is not None and self.max_tokens <= 0:
            raise ValueError(f"max_tokens must be positive, got {self.max_tokens}")
        if self.max_iterations < 1:
            raise ValueError(f"max_iterations must be >= 1, got {self.max_iterations}")
        if not 0.0 <= self.temperature <= 2.0:
            raise ValueError(f"temperature must be in [0.0, 2.0], got {self.temperature}")

        # Mode C validation — tools + tool_registry mutually exclusive
        if self.tools and self.tool_registry is not None:
            raise ValueError(
                "Cannot mix `tools=` (Mode A/B) and `tool_registry=` (Mode C). "
                "Pick one — pre-built registry skips list introspection."
            )

        # Mode 2 validation
        if self.instructions and self.system is not None:
            raise ValueError(
                "Cannot mix Mode 1 (`instructions=`) and Mode 2 (`system=`). "
                "Pick one — `instructions` is shorthand for `system`."
            )
        if self.examples is not None:
            for i, ex in enumerate(self.examples):
                if not isinstance(ex, dict) or "user" not in ex or "assistant" not in ex:
                    raise ValueError(
                        f"examples[{i}] malformed: must be dict with `user` "
                        f"and `assistant` keys. Got: {ex!r}"
                    )

    def _build_tool_registry(self) -> ToolRegistry:
        """Build registry from one of: Mode C (passed), Mode A/B (list), or empty.

        Mode D (YAML tool schemas) is layered on top in `_apply_yaml_tool_schemas`.
        """
        # Mode C: user provided pre-built registry — use directly
        if self.tool_registry is not None:
            registry = self.tool_registry
        else:
            registry = ToolRegistry()
            # Mode A (callable) + Mode B (ITool) heterogeneous list
            for item in self.tools:
                if isinstance(item, ITool):
                    # Mode B: ITool instance — register as-is (schema already attached)
                    registry.register(item.tool_id, item)
                else:
                    # Mode A: callable — wrap + auto-introspect schema
                    schema = build_tool_schema(item)
                    registry.register(item.__name__, item)
                    handler = registry._handlers[item.__name__]
                    handler.schema = schema  # type: ignore[attr-defined]

        # Mode D: if Mode 4 (YAML prompt) active, attach YAML schemas by name
        self._apply_yaml_tool_schemas(registry)
        return registry

    def _apply_yaml_tool_schemas(self, registry: ToolRegistry) -> None:
        """Mode D: attach YAML tool schemas to existing registry handlers.

        Behavior:
          - Mode 4 active + user opted into tools (via `tools=` OR `tool_registry=`)
            → strict pairing: every YAML tool must have a handler, else ValueError.
          - Mode 4 active + user did NOT pass tools/registry → silently skip YAML
            tools (user signals "prompts only").
        """
        if self.prompt is None or self._yaml_tools_cache is None:
            return
        # User opted out: no tool_registry, no tools list → ignore YAML tools
        if self.tool_registry is None and not self.tools:
            return

        from ryuu.prompts.models import ToolDefinition

        for tool_def in self._yaml_tools_cache:
            assert isinstance(tool_def, ToolDefinition)
            handler = registry._handlers.get(tool_def.name)
            if handler is None:
                raise ValueError(
                    f"YAML defines tool {tool_def.name!r} but no handler registered. "
                    f"Add `{tool_def.name}` to your ToolRegistry or remove from YAML."
                )
            handler.schema = tool_def.to_openai_schema()  # type: ignore[attr-defined]

    def _build_hook_registry(self) -> HookRegistry | None:
        """Build HookRegistry from `hooks={"event": [handlers]}` dict.

        Returns None if hooks is empty/missing — internal agent skips firing
        when registry is None for zero overhead.
        """
        if not self.hooks:
            return None
        registry = HookRegistry()
        registry.register_dict(self.hooks)   # type: ignore[arg-type]
        return registry

    def _wrap_tool_registry_with_hooks(
        self, tool_registry: ToolRegistry, hook_registry: HookRegistry | None,
        scope: ContextScope | None = None,
    ) -> None:
        """Phase 9.2: wrap each handler in ToolRegistry to fire PRE_TOOL/POST_TOOL.

        Mutation: PRE_TOOL handler can replace `args` via `ctx.replace(args=...)`.
        Block: PRE_TOOL handler can raise to abort tool call.
        """
        if hook_registry is None:
            return
        if not (hook_registry.has_handlers(HookEvent.PRE_TOOL) or
                hook_registry.has_handlers(HookEvent.POST_TOOL)):
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

    def _build_cross_cutting(self) -> tuple[Any, Any, Any, Any]:
        from ryuu_core.nulls import (
            NullAuditLogger,
            NullCostTracker,
            NullRateLimiter,
            NullTracer,
        )

        cost: Any = NullCostTracker()
        if self.budget_usd is not None:
            from ryuu_observability.cost import CostPolicy, CostTracker

            # `budget_usd` maps to per-user-per-day cap (closest semantic for
            # a session budget — CostPolicy doesn't have a per-session field).
            cost = CostTracker(CostPolicy(per_user_per_day_usd=self.budget_usd))

        rate: Any = NullRateLimiter()
        if self.rate_limit_rps is not None:
            from ryuu_observability.rate_limit import RateLimiter, RatePolicy

            rate = RateLimiter(RatePolicy(rps=self.rate_limit_rps))

        audit: Any = NullAuditLogger()
        if self.audit:
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
        if self.trace:
            from ryuu_observability.tracer import Tracer

            tracer = Tracer()

        return cost, rate, audit, tracer
