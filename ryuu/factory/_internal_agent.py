"""_FactoryLLMAgent — concrete LLMAgent subclass owned by Factory.

Private internal class. Users interact via `Agent` (factory facade); this
class implements the actual LLM dispatch loop, hooks, failover, and parsing.

Holds Factory-specific config (system_prompt, examples, max_tokens, temperature,
max_iterations) that flow into CompletionRequest + ReAct loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ryuu_core.models import AgentResult, Cost, Task
from ryuu_execution.llm_agent import LLMAgent
from ryuu_providers.llm import CompletionRequest, ILLMProvider, Message
from ryuu_workflow.context import ExecutionContext

from ryuu.hooks import (
    HookEvent,
    HookRegistry,
    OnBudgetExceededContext,
    OnCompleteContext,
    OnErrorContext,
    OnRateLimitedContext,
    PostExecuteContext,
    PostLLMContext,
    PreExecuteContext,
    PreLLMContext,
)


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
    _thinking_mode: bool = False   # Phase 14.1 — populated from Factory.thinking_mode
    _output_schema: dict[str, Any] | None = None   # Phase 11.y — JSON Schema for structured output

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
        # Phase 14.1 — thinking_mode injects <thinking>/<answer> instruction.
        # Layer B (ergonomic): augment system_prompt; parse output post-call.
        effective_system = self.system_prompt
        if self._thinking_mode:
            from ryuu._thinking_parser import wrap_thinking_template

            effective_system = wrap_thinking_template(effective_system)
        if effective_system:
            messages.append(Message(role="system", content=effective_system))

        # Few-shot examples interleave as alternating user/assistant pairs
        # BEFORE the real user query — OpenAI convention.
        if self.examples:
            for ex in self.examples:
                messages.append(Message(role="user", content=ex["user"]))
                messages.append(Message(role="assistant", content=ex["assistant"]))

        messages.append(Message(role="user", content=user_content))

        # ── Fire PRE_LLM ──
        # Declared before the guard so Pyright knows it's always bound when
        # _hook_registry is not None (required for apply_llm_wraps below).
        pre_llm_ctx: PreLLMContext | None = None
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
            response_schema=self._output_schema,   # Phase 11.y
        )

        # Phase 10.6 + 9.3: failover wrapped by LLM middleware chain if registered.
        if self._hook_registry is not None and self._hook_registry.has_llm_wraps():
            assert pre_llm_ctx is not None  # always true: registry is not None → ctx was built above
            async def _do_llm(ctx: PreLLMContext) -> Any:
                return await self._react_loop_with_failover(
                    request, domain=context.scope.domain
                )
            output, usage = await self._hook_registry.apply_llm_wraps(
                pre_llm_ctx, _do_llm
            )
        else:
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

        # Resolve $ via the central pricing table. Returns 0.0 for unknown
        # models — callers can still inspect input_tokens/output_tokens directly.
        from ryuu_providers_core._pricing import calculate_usd

        cost = Cost(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            usd=calculate_usd(self._model_name, usage.input_tokens, usage.output_tokens),
            provider=self.llm.__class__.__name__.replace("Provider", "").lower(),
            model=self._model_name,
        )

        # Phase 14.1 — parse <thinking>/<answer> tags when thinking_mode active.
        # Fallback: if tags absent, keep raw output; thinking="" (graceful degrade).
        thinking_text = ""
        final_output = output
        if self._thinking_mode:
            from ryuu._thinking_parser import parse_thinking_answer

            final_output, thinking_text = parse_thinking_answer(output)

        # Phase 11.y — auto-parse JSON when output_schema active.
        # Best-effort: if parse fails, keep raw output in `output`, parsed=None.
        parsed_obj: Any = None
        if self._output_schema is not None:
            import json
            try:
                stripped = str(final_output).strip()
                # Strip ```json fences if model returned wrapped JSON
                if stripped.startswith("```"):
                    lines = stripped.split("\n")
                    if len(lines) > 2:
                        stripped = "\n".join(lines[1:-1])
                parsed_obj = json.loads(stripped)
            except (json.JSONDecodeError, ValueError):
                parsed_obj = None

        return AgentResult(
            task_id=task.task_id,
            output=final_output,
            cost=cost,
            thinking=thinking_text,
            parsed=parsed_obj,
        )

