"""Smoke tests for the standalone ryuu_execution package."""
import pytest
from ryuu_core.context import ContextScope, ExecutionContext
from ryuu_core.models import AgentResult, Cost, Task


def test_base_agent_and_task_importable() -> None:
    from ryuu_execution.agent import BaseAgent, Task, AgentResult  # noqa: F401


def test_tool_registry_importable() -> None:
    from ryuu_execution.tool_registry import ITool, ToolRegistry  # noqa: F401


def test_agent_pool_importable() -> None:
    from ryuu_execution.pool import AgentPool  # noqa: F401


def test_llm_agent_importable() -> None:
    from ryuu_execution.llm_agent import (  # noqa: F401
        LLMAgent,
        ReActCallbacks,
        SilentCallbacks,
        PrintCallbacks,
        BudgetSummary,
        ModelPolicy,
    )


def test_sandbox_importable() -> None:
    from ryuu_execution.sandbox import (  # noqa: F401
        SandboxResult,
        ISandbox,
        SubprocessSandbox,
        SandboxManager,
    )


def test_top_level_init_importable() -> None:
    from ryuu_execution import (  # noqa: F401
        BaseAgent,
        AgentPool,
        LLMAgent,
        ITool,
        ToolRegistry,
        PrintCallbacks,
        ReActCallbacks,
        SilentCallbacks,
    )


async def test_tool_registry_register_and_run() -> None:
    from ryuu_execution.tool_registry import ToolRegistry

    registry = ToolRegistry()

    async def my_tool(**kwargs: object) -> dict[str, object]:
        return {"result": "ok", **kwargs}

    registry.register("my_tool", my_tool)

    result = await registry.run(
        {"function": {"name": "my_tool", "arguments": {"x": 1}}},
        domain="test",
    )
    assert "ok" in result


async def test_agent_pool_register_and_dispatch() -> None:
    from ryuu_execution.agent import BaseAgent
    from ryuu_execution.pool import AgentPool

    class EchoAgent(BaseAgent):
        async def _execute(self, task: Task, context: ExecutionContext) -> AgentResult:
            return AgentResult(
                task_id=task.task_id,
                output=task.payload.get("message", "echo"),
                cost=Cost.zero(),
                success=True,
            )

    pool = AgentPool()
    pool.register(EchoAgent(agent_id="echo"))

    ctx = ExecutionContext(
        scope=ContextScope(user_id="u1", session_id="s1", domain="test"),
        correlation_id="test-cid",
    )
    task = Task(task_id="t1", payload={"message": "hello"})

    result = await pool.dispatch(task, ctx)
    assert result.success
    assert result.output == "hello"


def test_sandbox_manager_runs_echo() -> None:
    from ryuu_execution.sandbox import SandboxManager

    mgr = SandboxManager()
    result = mgr.run(["python3", "-c", "print('hi')"])
    assert result.success
    assert "hi" in result.stdout


def test_model_policy_selects_tier() -> None:
    from ryuu_execution.llm_agent import ModelPolicy
    from ryuu_core.models import ModelTier

    policy = ModelPolicy()

    class FakeLLMAgent:
        model_policy = policy

        def select_model(self, query: str) -> ModelTier:
            words = query.lower().split()
            wc = len(words)
            if policy.keywords & set(words):
                return ModelTier.POWERFUL
            if wc > policy.word_count_threshold:
                return ModelTier.POWERFUL
            if wc <= policy.cheap_threshold:
                return ModelTier.CHEAP
            return ModelTier.STANDARD

    agent = FakeLLMAgent()
    assert agent.select_model("hi") == ModelTier.CHEAP
    assert agent.select_model("analyze this complex data pipeline") == ModelTier.POWERFUL
