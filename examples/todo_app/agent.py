"""TodoAnalysisAgent — extends LLMAgent, provides domain-specific ingest + analysis."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from examples.todo_app.models import Goal
from uaaf.execution.agent import AgentResult, Task
from uaaf.execution.llm_agent import LLMAgent
from uaaf.intent.models import ModelTier
from uaaf.knowledge.context_assembler import ContextAssembler
from uaaf.knowledge.memory.backbone import MemoryBackbone
from uaaf.observability._pricing import calculate_usd
from uaaf.observability.cost import Cost
from uaaf.prompts.registry import PromptRegistry
from uaaf.providers.llm import CompletionRequest, ILLMProvider, TokenUsage
from uaaf.runtime.context import ExecutionContext

_PROMPTS_ROOT = Path(__file__).parent.parent.parent / "prompts"
_registry = PromptRegistry(prompts_root=_PROMPTS_ROOT)

# Maps ModelTier → concrete OpenAI model string for this example.
# Projects using ModelRouter don't need this — the router handles tier routing.
_TIER_TO_MODEL: dict[ModelTier, str] = {
    ModelTier.CHEAP:    "gpt-4o-mini",
    ModelTier.STANDARD: "gpt-4o-mini",
    ModelTier.POWERFUL: "gpt-4o",
}


def build_provider() -> ILLMProvider:
    """Return OpenAIProvider if OPENAI_API_KEY is set, FakeLLMProvider otherwise."""
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        from uaaf.providers.adapters.openai import OpenAIProvider
        print("  🔑 Using OpenAIProvider (OPENAI_API_KEY found)")
        return OpenAIProvider(api_key=api_key)  # type: ignore[return-value]

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
class TodoAnalysisAgent(LLMAgent):
    """Analyzes goal/task portfolio. Extends LLMAgent for react_loop + model selection."""

    assembler: ContextAssembler = field(
        default_factory=lambda: ContextAssembler(MemoryBackbone())
    )
    prompt_version: str = "v1"

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

        # 1. Dynamic model selection via framework
        tier = self.select_model(query)
        model = _TIER_TO_MODEL[tier]
        print(f"  🧠 Model selection: {tier.value} → {model}  ({len(query.split())} words)")

        # 2. Load versioned prompt + assemble context
        cfg = _registry.load("todo_app", self.prompt_version)
        assembled = await self.assembler.assemble(
            query=query, scope_key=scope_key, budget_tokens=3000,
        )
        print(f"  📚 Context assembled: {assembled.token_count} tokens from memory")

        # 3. Build CompletionRequest with tier-based model
        base_request = _registry.build_request(
            cfg, prompt_name,
            include_tools=bool(self.tool_registry and self.tool_registry._handlers),
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

        # 4. ReAct loop via framework (callbacks injected at construction)
        response, usage = await self.react_loop(request, max_rounds=3, domain="todo")

        # 5. Token budget display
        summary = self.budget_summary(usage, model)
        print(
            f"\n  📊 Token budget: {summary.input_tokens:,} in + {summary.output_tokens:,} out"
            f" = {summary.total_tokens:,} total  |  window: {summary.window_size // 1_000}K"
            f"  |  {summary.pct_used:.1f}% used"
        )

        usd = calculate_usd(cfg.model, usage.input_tokens, usage.output_tokens)
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
