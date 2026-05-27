"""LLMAgent — BaseAgent subclass providing _react_loop() for tool-calling agents."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ryuu_core.context import ExecutionContext
from ryuu_core.models import ModelTier, AgentResult, Task
from ryuu_execution.agent import BaseAgent
from ryuu_execution.tool_registry import ToolRegistry
from ryuu_providers._pricing import CONTEXT_WINDOW
from ryuu_providers.llm import (
    CompletionRequest,
    ILLMProvider,
    Message,
    TokenUsage,
)

_DEFAULT_CONTEXT_WINDOW = 128_000


@runtime_checkable
class ReActCallbacks(Protocol):
    """Hooks fired during _react_loop() — decouple display from LLM logic."""

    async def on_thought(self, text: str) -> None: ...
    async def on_action(self, tool_name: str, args: dict[str, Any]) -> None: ...
    async def on_observation(self, tool_name: str, result: str) -> None: ...
    async def on_final(self, text: str) -> None: ...


class SilentCallbacks:
    """No-op ReActCallbacks — default for tests and library code."""

    async def on_thought(self, text: str) -> None:
        pass

    async def on_action(self, tool_name: str, args: dict[str, Any]) -> None:
        pass

    async def on_observation(self, tool_name: str, result: str) -> None:
        pass

    async def on_final(self, text: str) -> None:
        pass


class PrintCallbacks:
    """Print ReActCallbacks for CLI usage. Outputs to stdout with icons."""

    async def on_thought(self, text: str) -> None:
        preview = text[:200] if len(text) > 200 else text
        if preview.strip():
            print(f"  💭 Thought: {preview}")

    async def on_action(self, tool_name: str, args: dict[str, Any]) -> None:
        import json
        print(f"  🔧 Action:      {tool_name}({json.dumps(args, ensure_ascii=False)})")

    async def on_observation(self, tool_name: str, result: str) -> None:
        preview = result if len(result) <= 300 else result[:297] + "..."
        print(f"  📋 Observation: {preview}")

    async def on_final(self, text: str) -> None:
        print(f"  ✅ Final answer: {text[:100]}" if len(text) > 100 else f"  ✅ Final answer: {text}")


@dataclass
class BudgetSummary:
    """Token budget snapshot after a _react_loop() call."""

    input_tokens: int
    output_tokens: int
    total_tokens: int
    window_size: int
    pct_used: float


_DEFAULT_COMPLEX_KEYWORDS: frozenset[str] = frozenset({
    "analyze", "compare", "evaluate", "explain", "breakdown",
    "strategy", "optimize", "tradeoff", "review", "diagnose",
})


@dataclass
class ModelPolicy:
    """Complexity rules for model tier selection."""

    keywords: set[str] = field(default_factory=lambda: set(_DEFAULT_COMPLEX_KEYWORDS))
    word_count_threshold: int = 25
    cheap_threshold: int = 5


@dataclass
class LLMAgent(BaseAgent):
    """Abstract agent with a built-in ReAct tool-calling loop."""

    llm: ILLMProvider = field(default=None)  # type: ignore[assignment]
    tool_registry: ToolRegistry | None = None
    model_policy: ModelPolicy = field(default_factory=ModelPolicy)
    callbacks: ReActCallbacks = field(default_factory=SilentCallbacks)
    audit_token_usage: bool = True

    @abstractmethod
    async def _execute(self, task: Task, context: ExecutionContext) -> AgentResult: ...

    def select_model(self, query: str) -> ModelTier:
        words = query.lower().split()
        word_count = len(words)
        if self.model_policy.keywords & set(words):
            return ModelTier.POWERFUL
        if word_count > self.model_policy.word_count_threshold:
            return ModelTier.POWERFUL
        if word_count <= self.model_policy.cheap_threshold:
            return ModelTier.CHEAP
        return ModelTier.STANDARD

    def budget_summary(self, usage: TokenUsage, model: str) -> BudgetSummary:
        total = usage.input_tokens + usage.output_tokens
        window = CONTEXT_WINDOW.get(model, _DEFAULT_CONTEXT_WINDOW)
        return BudgetSummary(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=total,
            window_size=window,
            pct_used=total / window * 100,
        )

    async def _react_loop(
        self,
        request: CompletionRequest,
        max_rounds: int = 3,
        domain: str = "",
        callbacks: ReActCallbacks | None = None,
    ) -> tuple[str, TokenUsage]:
        """Thought→Action→Observation loop. Returns (final_text, accumulated_usage)."""
        cb: ReActCallbacks = callbacks if callbacks is not None else self.callbacks
        messages = list(request.messages)
        total_input = 0
        total_output = 0

        for _ in range(1, max_rounds + 1):
            current_req = CompletionRequest(
                messages=messages,
                model=request.model,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                tools=request.tools,
                system=request.system,
                response_schema=request.response_schema,
            )
            response = await self.llm.complete(current_req)
            total_input += response.usage.input_tokens
            total_output += response.usage.output_tokens

            # Fire thinking blocks (extended thinking / CoT) before tool/final check
            for thinking_text in response.thinking:
                if thinking_text.strip():
                    await cb.on_thought(thinking_text)

            tool_calls: list[dict[str, Any]] = response.tool_calls or response.metadata.get("tool_calls", [])

            if not tool_calls:
                await cb.on_final(response.content)
                return response.content, TokenUsage(total_input, total_output)

            thought = response.content or ""
            if not thought.strip():
                names = [tc["function"]["name"] for tc in tool_calls]
                thought = "I'll use " + " + ".join(names) + " to gather the data I need."
            await cb.on_thought(thought)

            if self.tool_registry is None:
                await cb.on_final(response.content)
                return response.content, TokenUsage(total_input, total_output)

            tool_results = await self.tool_registry.run_all(tool_calls, domain=domain)

            for tc, tr in zip(tool_calls, tool_results, strict=False):
                fn = tc["function"]
                await cb.on_action(fn["name"], fn["arguments"])
                await cb.on_observation(fn["name"], tr["content"])

            messages.append(Message(
                role="assistant",
                content=response.content or "",
                tool_calls=tool_calls,
            ))
            for tc, tr in zip(tool_calls, tool_results, strict=False):
                messages.append(Message(
                    role="tool",
                    content=tr["content"],
                    tool_call_id=tc["id"],
                ))

        synthesis_req = CompletionRequest(
            messages=messages + [Message(role="user", content="Summarize your findings.")],
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            tools=None,
        )
        final = await self.llm.complete(synthesis_req)
        total_input += final.usage.input_tokens
        total_output += final.usage.output_tokens
        await cb.on_final(final.content)
        return final.content, TokenUsage(total_input, total_output)
