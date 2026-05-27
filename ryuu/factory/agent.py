"""Agent — public Factory class for lean single-agent + tool-calling use cases.

The main entry point for `ryuu.Agent(...)`. Composes provider auto-detect,
tool schema introspection, cross-cutting cost/audit/trace/rate-limit, hooks,
multi-prompt modes (1-4), multi-tool modes (A-D), streaming, failover,
and Phase 14.x cognitive strategy wires (thinking_mode, n_samples, adaptive_compute).

For advanced use cases (custom multi-step domain logic, custom strategies),
use class-based `BaseAgent` subclass — Agent does NOT replace it.

See: docs/guides/quickstart/01-factory.md
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import anyio

from ryuu_core.models import AgentResult, Task
from ryuu_execution.llm_agent import (
    PrintCallbacks,
    ReActCallbacks,
    SilentCallbacks,
)
from ryuu_execution.tool_registry import ITool, ToolRegistry
from ryuu_providers.llm import CompletionRequest, ILLMProvider, Message
from ryuu_workflow.context import ContextScope, ExecutionContext

from ryuu._provider_detect import build_provider
from ryuu._tool_introspect import build_tool_schema
from ryuu.factory._internal_agent import _FactoryLLMAgent
from ryuu.factory.stream_event import RESERVED_SCOPE_KEYS, StreamEvent
from ryuu.hooks import (
    HookEvent,
    HookRegistry,
    PostLLMContext,
    PostToolContext,
    PreLLMContext,
    PreToolContext,
)
from ryuu.prompts.registry import PromptRegistry


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

    # Phase 9.3 — wrap-style middleware. Handlers receive (next, ctx) and can
    # call next 0/1/N times (retry, fallback, circuit-breaker patterns).
    #   around_llm  — wraps the entire LLM call chain per execute()
    #   around_tool — wraps each individual tool handler call
    around_llm: list[Callable[..., Any]] | None = None
    around_tool: list[Callable[..., Any]] | None = None

    # Phase 14.1 — Thinking mode (Layer B ergonomic wire to ThinkingStrategy).
    # When True, Factory wraps execution with <thinking>/<answer> tags and
    # populates AgentResult.thinking. Internally creates a ThinkingStrategy
    # instance from ryuu-cognitive.
    thinking_mode: bool = False

    # Phase 14.2 — Best-of-N (Layer B ergonomic wire to BestOfNStrategy).
    # When n_samples > 1, Factory runs `n_samples` parallel calls and aggregates
    # via `vote` mode. `confidence_threshold` (reserved) gates whether to skip
    # best-of-N when primary call exceeds confidence.
    n_samples: int = 1
    vote: Literal["majority", "llm_judge", "score_fn"] = "majority"
    confidence_threshold: float | None = None
    score_fn: Callable[[str], float] | None = None   # for vote="score_fn"

    # Phase 14.3 — Adaptive Compute (Layer B ergonomic wire to AdaptiveStrategy).
    # When True, Factory runs cheap difficulty classifier first then dispatches
    # with tier-appropriate model + iterations + max_tokens. Default tier config:
    #   trivial → gpt-4o-mini, max_iter=2, max_tokens=300
    #   medium  → gpt-4o-mini, max_iter=4, max_tokens=800
    #   hard    → gpt-4o,       max_iter=8, max_tokens=2000
    adaptive_compute: bool = False
    difficulty_fn: Callable[[str], str] | None = None
    tier_models: dict[str, str] | None = None
    tier_max_iterations: dict[str, int] | None = None
    tier_max_tokens: dict[str, int] | None = None

    # Phase 14.x — Explicit strategy override (advanced — Option A escape hatch).
    # If set, Factory uses this strategy instance instead of inferring from
    # kwargs. Mutually exclusive with thinking_mode (and future n_samples,
    # adaptive_compute kwargs). Set to ICognitiveStrategy instance.
    strategy: Any = None

    # Phase 11.x — RAG knowledge backbone (RAGBackbone or any IKnowledgeBackbone).
    # When set, Factory pre-fetches `assemble_context(query, scope_key, budget)`
    # on every `.run()` call and prepends to user_content for grounding.
    # Scope key resolved from ContextScope via `knowledge_scope_field`.
    knowledge: Any = None
    knowledge_budget_tokens: int = 2000
    knowledge_scope_field: Literal["user_id", "session_id", "domain"] = "domain"

    # Phase 11.y — Structured output (JSON Schema enforcement).
    # When set, Factory forwards to CompletionRequest.response_schema:
    #   - OpenAI gpt-4o+: strict `response_format={"type": "json_schema", ...}`
    #   - OpenAI legacy: basic `response_format={"type": "json_object"}` fallback
    #   - Anthropic: tool-use trick (1 tool, forced choice) — strict enforcement
    # AgentResult.parsed populated với json.loads(output) when successful.
    output_schema: dict[str, Any] | None = None

    # Internal — built lazily, exposed for tests
    _agent: _FactoryLLMAgent = field(init=False, repr=False)
    # Mode D: cache of YAML tool defs (populated by _resolve_yaml_prompt)
    _yaml_tools_cache: list[Any] | None = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        from ryuu.factory import _builders, _resolvers

        # Mode 3: resolve Path → file contents before validation so downstream
        # logic only ever sees str | None.
        _resolvers.resolve_file_paths(self)
        # Mode 4: load from YAML registry — sets system + user_template before
        # validate() so the resolved fields are subject to the same checks.
        _resolvers.resolve_yaml_prompt(self)
        _resolvers.validate(self)

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
        tool_registry = _builders.build_tool_registry(self)
        hook_registry = _builders.build_hook_registry(self)
        # Phase 9.2: install PRE_TOOL/POST_TOOL wrappers on tool handlers
        _builders.wrap_tool_registry_with_hooks(tool_registry, hook_registry)
        cost, rate, audit, tracer = _builders.build_cross_cutting(self)

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
            _thinking_mode=self.thinking_mode,
            _output_schema=self.output_schema,
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

        # ── Fire PRE_LLM (mirrors _run_inner; allows message mutation) ──
        pre_llm_ctx: PreLLMContext | None = None
        hook_reg = self._agent._hook_registry
        if hook_reg is not None:
            pre_llm_ctx = PreLLMContext(
                event=HookEvent.PRE_LLM,
                correlation_id="",
                scope=ContextScope(user_id="", session_id="", domain=""),
                messages=messages,
                model=model_name,
            )
            await hook_reg.fire(HookEvent.PRE_LLM, pre_llm_ctx)
            messages = pre_llm_ctx.messages  # accept mutations

        request = CompletionRequest(
            messages=messages, model=model_name,
            temperature=self.temperature, max_tokens=self.max_tokens, tools=None,
        )

        # ── LLM wrap chain (streaming variant) ──
        # next(ctx) in wrap handlers returns AsyncIterator[StreamChunk].
        if hook_reg is not None and hook_reg.has_llm_wraps():
            assert pre_llm_ctx is not None

            async def _get_stream(ctx: PreLLMContext) -> Any:
                return self._agent.llm.stream(request)

            raw_stream = await hook_reg.apply_llm_wraps(pre_llm_ctx, _get_stream)
        else:
            raw_stream = self._agent.llm.stream(request)

        full_text_parts: list[str] = []
        async for chunk in raw_stream:
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

        # Phase 11.x — RAG knowledge injection. Pre-fetch context + prepend.
        if self.knowledge is not None:
            user_content = await self._inject_knowledge(user_content, scope)

        # Phase 14.3 — Adaptive compute: classify difficulty → swap tier fields
        if self.adaptive_compute:
            return await self._run_adaptive(user_content, ctx)

        # Phase 14.2 — Best-of-N: run N concurrent calls + aggregate
        if self.n_samples > 1:
            return await self._run_best_of_n(user_content, ctx)

        task = Task(task_id=str(uuid.uuid4()), payload={"user_content": user_content})
        return await self._agent.execute(task, ctx)

    async def _inject_knowledge(
        self, user_content: str, scope: ContextScope
    ) -> str:
        """Phase 11.x — Pre-fetch RAG context via IKnowledgeBackbone.

        Resolves scope_key from scope (default: domain). Calls
        `knowledge.assemble_context(query, scope_key, budget_tokens)`. Prepends
        as 'Context:\\n{text}\\n---\\nQuery:\\n{original}'.

        Empty/zero results → return user_content unchanged (no leading 'Context:'
        block when there's nothing to inject).
        """
        scope_key = getattr(scope, self.knowledge_scope_field, "default")
        assembled = await self.knowledge.assemble_context(
            query=user_content,
            scope_key=scope_key,
            budget_tokens=self.knowledge_budget_tokens,
        )
        if not assembled.text.strip():
            return user_content
        return (
            f"Context (retrieved knowledge):\n{assembled.text}\n"
            f"---\n"
            f"Query:\n{user_content}"
        )

    async def _run_adaptive(
        self, user_content: str, ctx: ExecutionContext
    ) -> AgentResult:
        """Phase 14.3 — Classify difficulty + swap tier model/iterations/max_tokens."""
        from ryuu._difficulty_classifier import normalize_difficulty

        tier_models = self.tier_models or {
            "trivial": "gpt-4o-mini", "medium": "gpt-4o-mini", "hard": "gpt-4o",
        }
        tier_max_iter = self.tier_max_iterations or {"trivial": 2, "medium": 4, "hard": 8}
        tier_max_tok = self.tier_max_tokens or {"trivial": 300, "medium": 800, "hard": 2000}

        if self.difficulty_fn is None:
            raise ValueError(
                "adaptive_compute=True requires difficulty_fn. "
                "Pass difficulty_fn=<callable str->'trivial'|'medium'|'hard'>, "
                "e.g. backed by ryuu-intent LLM difficulty classifier."
            )
        difficulty = self.difficulty_fn(user_content)

        # Swap internal agent fields temporarily
        original_model = self._agent._model_name
        original_max_iter = self._agent._max_iterations
        original_max_tok = self._agent._max_tokens

        self._agent._model_name = tier_models[difficulty]
        self._agent._max_iterations = tier_max_iter[difficulty]
        self._agent._max_tokens = tier_max_tok[difficulty]

        try:
            task = Task(
                task_id=str(uuid.uuid4()),
                payload={"user_content": user_content},
            )
            result = await self._agent.execute(task, ctx)
            result.metadata["difficulty"] = difficulty
            result.metadata["tier_model"] = tier_models[difficulty]
            return result
        finally:
            # Restore for next call
            self._agent._model_name = original_model
            self._agent._max_iterations = original_max_iter
            self._agent._max_tokens = original_max_tok

    async def _run_best_of_n(
        self, user_content: str, ctx: ExecutionContext
    ) -> AgentResult:
        """Phase 14.2 — Sample N times concurrently + aggregate via vote."""
        import asyncio
        from collections import Counter

        async def _one() -> AgentResult:
            task = Task(
                task_id=str(uuid.uuid4()),
                payload={"user_content": user_content},
            )
            return await self._agent.execute(task, ctx)

        results = await asyncio.gather(*(_one() for _ in range(self.n_samples)))
        samples = [str(r.output) for r in results]

        if self.vote == "majority":
            counts = Counter(samples)
            winner, count = counts.most_common(1)[0]
            confidence = count / len(samples)
        elif self.vote == "score_fn":
            if self.score_fn is None:
                raise ValueError("vote='score_fn' requires score_fn callable")
            score_fn = self.score_fn
            winner = max(samples, key=score_fn)
            confidence = float(score_fn(winner))
        elif self.vote == "llm_judge":
            raise NotImplementedError(
                "vote='llm_judge' Factory wire deferred — use BestOfNStrategy directly"
            )
        else:
            winner, confidence = samples[0], 1.0

        # Use cost of first result as proxy; metadata records all samples
        primary = results[0]
        primary.metadata.setdefault("samples", samples)
        primary.metadata["best_of_n_confidence"] = confidence
        primary.output = winner
        return primary

