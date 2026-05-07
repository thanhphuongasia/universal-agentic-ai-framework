"""TodoAnalysisAgent — refactored to use PromptRegistry + OpenAI + tool calling."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from examples.todo_app.models import Goal
from examples.todo_app.tools import ToolRegistry
from uaaf.execution.agent import AgentResult, BaseAgent, Task
from uaaf.knowledge.context_assembler import ContextAssembler
from uaaf.knowledge.memory.backbone import MemoryBackbone
from uaaf.observability._pricing import calculate_usd
from uaaf.observability.cost import Cost
from uaaf.prompts.registry import PromptRegistry
from uaaf.providers.llm import CompletionRequest, ILLMProvider, Message, TokenUsage
from uaaf.runtime.context import ExecutionContext

# Prompt registry — loaded once, shared across agent instances
_PROMPTS_ROOT = Path(__file__).parent.parent.parent / "prompts"
_registry = PromptRegistry(prompts_root=_PROMPTS_ROOT)

# Context window sizes (tokens) per model family
_CONTEXT_WINDOW: dict[str, int] = {
    "gpt-4o":      128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
}

# Keywords that signal a complex query requiring the larger model
_COMPLEX_KEYWORDS = {
    "analyze", "compare", "evaluate", "explain", "breakdown",
    "strategy", "optimize", "tradeoff", "review", "diagnose",
}


def build_provider() -> ILLMProvider:
    """Return OpenAIProvider if OPENAI_API_KEY is set, FakeLLMProvider otherwise."""
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        from uaaf.providers.adapters.openai import OpenAIProvider
        print("  🔑 Using OpenAIProvider (OPENAI_API_KEY found)")
        return OpenAIProvider(api_key=api_key)  # type: ignore[return-value]
    else:
        from uaaf._testing.fakes import FakeLLMProvider
        from uaaf.providers.llm import Response

        def _r(t: str) -> Response:
            return Response(content=t, model="fake", usage=TokenUsage(80, 60), finish_reason="stop")

        print("  ⚠️  OPENAI_API_KEY not set — using FakeLLMProvider (demo mode)")
        return FakeLLMProvider(responses=[  # type: ignore[return-value]
            _r("## Analysis\nMVP goal is 71% done. Backend tasks run ~1.3x over estimate. "
               "Focus next: Deploy to production (CRITICAL blocker)."),
            _r(json.dumps({"by_priority": {"critical": 3, "high": 6, "medium": 2, "low": 1},
                           "effort_by_goal": {"g1": 35.0, "g2": 15.0, "g3": 7.5},
                           "completion_rate_by_goal": {"g1": 71.4, "g2": 80.0, "g3": 60.0}})),
            _r("1. Deploy to production (CRITICAL, g1 blocker)\n"
               "2. Async DB migration (HIGH, g2, 37% done)\n"
               "3. Onboarding emails (MEDIUM, g1, 0h)"),
        ])


@dataclass
class TodoAnalysisAgent(BaseAgent):
    """
    Analyzes goal/task portfolio using:
      • MemoryBackbone — stores all tasks as observations
      • PromptRegistry — loads versioned prompts from YAML
      • ILLMProvider   — OpenAI (production) or Fake (test)
      • ToolRegistry   — executes tool_calls from LLM responses
    """
    llm: ILLMProvider = field(default_factory=build_provider)
    assembler: ContextAssembler = field(
        default_factory=lambda: ContextAssembler(MemoryBackbone())
    )
    tool_registry: ToolRegistry = field(default_factory=ToolRegistry)
    prompt_version: str = "v1"

    @staticmethod
    def _select_model(query: str) -> str:
        """Choose model based on query complexity.

        Long queries or those containing analytical keywords get gpt-4o;
        everything else uses gpt-4o-mini to save cost.
        """
        words = query.lower().split()
        is_complex = len(words) > 25 or bool(_COMPLEX_KEYWORDS & set(words))
        model = "gpt-4o" if is_complex else "gpt-4o-mini"
        label = "complex → gpt-4o" if is_complex else "simple → gpt-4o-mini"
        print(f"  🧠 Model selection: {label}  ({len(words)} words)")
        return model

    async def ingest_goals(self, goals: list[Goal], scope_key: str) -> None:
        """Ingest all goals + tasks into MemoryBackbone."""
        for goal in goals:
            await self.assembler.write(
                observation=(
                    f"[GOAL:{goal.goal_id}] {goal.name} | priority={goal.priority} | "
                    f"completion={goal.completion_rate * 100:.0f}% | "
                    f"tasks={len(goal.tasks)} | deadline={goal.deadline}"
                ),
                scope_key=scope_key,
                metadata={"type": "goal", "goal_id": goal.goal_id},
            )
            for task in goal.tasks:
                await self.assembler.write(
                    observation=(
                        f"[TASK:{task.task_id}] {task.title} | "
                        f"goal={task.goal_id} | priority={task.priority} | "
                        f"status={task.status} | "
                        f"effort={task.actual_hours:.1f}h/{task.effort_hours:.1f}h | "
                        f"ratio={task.effort_ratio:.2f} | tags={','.join(task.tags)}"
                    ),
                    scope_key=scope_key,
                    metadata={"type": "task", "task_id": task.task_id, "goal_id": task.goal_id},
                )

    async def _execute(self, task: Task, context: ExecutionContext) -> AgentResult:
        query = str(task.payload.get("query", "Analyze my tasks"))
        prompt_name = str(task.payload.get("prompt", "analyze"))
        scope_key = context.scope.session_id

        # 1. Dynamic model selection based on query complexity
        model = self._select_model(query)

        # 2. Load versioned prompt config from YAML
        cfg = _registry.load("todo_app", self.prompt_version)

        # 3. Retrieve relevant context from memory
        assembled = await self.assembler.assemble(
            query=query, scope_key=scope_key, budget_tokens=3000,
        )
        print(f"  📚 Context assembled: {assembled.token_count} tokens from memory")

        # 4. Build CompletionRequest with dynamically selected model
        base_request = _registry.build_request(
            cfg, prompt_name,
            include_tools=bool(self.tool_registry._handlers),
            context=assembled.text,
            query=query,
        )
        request = CompletionRequest(
            messages=base_request.messages,
            model=model,
            temperature=base_request.temperature,
            max_tokens=base_request.max_tokens,
            tools=base_request.tools,
        )

        # 5. ReAct loop — returns final text + real token usage
        response, usage = await self._tool_loop(request, max_rounds=3)

        # 6. Token budget display
        window = _CONTEXT_WINDOW.get(model, 128_000)
        total_tokens = usage.input_tokens + usage.output_tokens
        pct = total_tokens / window * 100
        print(
            f"\n  📊 Token budget: {usage.input_tokens:,} in + {usage.output_tokens:,} out"
            f" = {total_tokens:,} total  |  window: {window // 1_000}K  |  {pct:.1f}% used"
        )

        usd = calculate_usd(model, usage.input_tokens, usage.output_tokens)
        return AgentResult(
            task_id=task.task_id,
            output=response,
            cost=Cost(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                usd=usd,
                provider="openai",
                model=model,
            ),
        )

    async def _tool_loop(
        self, request: CompletionRequest, max_rounds: int = 3
    ) -> tuple[str, TokenUsage]:
        """ReAct loop: Thought → Action → Observation → repeat until final answer."""
        messages = list(request.messages)
        cfg = _registry.load("todo_app", self.prompt_version)
        total_input = 0
        total_output = 0

        for round_num in range(1, max_rounds + 1):
            print(f"\n  ── ReAct round {round_num} ──────────────────────────────────")
            current_req = CompletionRequest(
                messages=messages,
                model=request.model,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                tools=request.tools,
            )
            response = await self.llm.complete(current_req)
            total_input += response.usage.input_tokens
            total_output += response.usage.output_tokens

            tool_calls = response.metadata.get("tool_calls", [])

            if not tool_calls:
                print(f"  ✅ Final answer (no tool calls needed)")
                return response.content, TokenUsage(total_input, total_output)

            # Thought step — what the LLM said before calling tools
            thought = response.content or "(selecting tools...)"
            if thought.strip():
                print(f"  💭 Thought: {thought[:200]}")

            # Action + Observation steps
            tool_results = await self.tool_registry.run_all(tool_calls)
            for tc, tr in zip(tool_calls, tool_results):
                fn = tc["function"]
                args_str = json.dumps(fn["arguments"], ensure_ascii=False)
                print(f"  🔧 Action:      {fn['name']}({args_str})")
                obs = tr["content"]
                # Truncate long observations for readability
                preview = obs if len(obs) <= 300 else obs[:297] + "..."
                print(f"  📋 Observation: {preview}")

            # Append assistant + tool messages for next round
            messages.append(Message(
                role="assistant", content=response.content or "", tool_calls=tool_calls,
            ))
            for tc, tr in zip(tool_calls, tool_results):
                messages.append(Message(
                    role="tool",
                    content=tr["content"],
                    tool_call_id=tc["id"],
                ))

        # Max rounds exceeded — ask for final synthesis without tools
        print(f"  ⚠️  Max rounds reached, requesting final synthesis")
        final_req = CompletionRequest(
            messages=messages + [Message(role="user", content="Summarize your findings.")],
            model=cfg.model,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
        )
        final = await self.llm.complete(final_req)
        total_input += final.usage.input_tokens
        total_output += final.usage.output_tokens
        return final.content, TokenUsage(total_input, total_output)
