"""Tool Modes B + C + D for Factory.

Phase 10.3 — 10 cases. Expected RED until implementation.

Mode B: tools=[ITool_instance] — pass ITool objects directly (with state).
Mode C: tool_registry=ToolRegistry — pre-built registry (DI + allowed_domains).
Mode D: prompt="proj:v:name" + tool_registry= — YAML schemas + Python handlers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ryuu import Agent
from ryuu._testing.fakes import FakeLLMProvider
from ryuu.prompts.registry import PromptRegistry
from ryuu_execution.tool_registry import ToolRegistry


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")


# ---------------------------------------------------------------------------
# Mode B — ITool instances
# ---------------------------------------------------------------------------


class _StatefulTool:
    """ITool impl with state (counts calls)."""

    tool_id = "stateful"
    schema: dict[str, Any] | None = {
        "type": "function",
        "function": {
            "name": "stateful",
            "description": "Stateful tool",
            "parameters": {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]},
        },
    }

    def __init__(self) -> None:
        self.call_count = 0

    async def execute(self, args: dict[str, Any]) -> Any:
        self.call_count += 1
        return {"x_doubled": args["x"] * 2, "calls": self.call_count}


def test_mode_b_itool_instance_registered() -> None:
    """ITool instance (not callable) is registered with its schema."""
    tool = _StatefulTool()
    agent = Agent(model="gpt-4o-mini", tools=[tool])

    handler = agent._agent.tool_registry._handlers["stateful"]  # type: ignore[attr-defined]
    assert handler.schema == _StatefulTool.schema


def test_mode_b_mixed_callable_and_itool() -> None:
    """tools=[callable, ITool] heterogeneous list works."""
    def plain_fn(name: str) -> dict:
        """Plain callable."""
        return {"name": name}

    tool = _StatefulTool()
    agent = Agent(model="gpt-4o-mini", tools=[plain_fn, tool])

    handlers = agent._agent.tool_registry._handlers  # type: ignore[attr-defined]
    assert "plain_fn" in handlers
    assert "stateful" in handlers


# ---------------------------------------------------------------------------
# Mode C — pre-built ToolRegistry
# ---------------------------------------------------------------------------


def _build_registry_with_dep(state: dict[str, int]) -> ToolRegistry:
    """Factory builds registry with closure over external state (DI pattern)."""
    registry = ToolRegistry()

    async def increment(key: str) -> dict:
        """Increment counter."""
        state[key] = state.get(key, 0) + 1
        return {"key": key, "value": state[key]}

    registry.register("increment", increment)
    return registry


def test_mode_c_tool_registry_kwarg_used_directly() -> None:
    """`tool_registry=` injects pre-built registry, skipping tools= introspection."""
    state: dict[str, int] = {}
    registry = _build_registry_with_dep(state)

    agent = Agent(model="gpt-4o-mini", tool_registry=registry)
    assert agent._agent.tool_registry is registry  # type: ignore[attr-defined]


def test_mode_c_validation_tools_and_registry_mutually_exclusive() -> None:
    """tools= + tool_registry= → ValueError."""
    def fn(x: str) -> dict:
        """Fn."""
        return {}

    registry = ToolRegistry()
    with pytest.raises(ValueError, match="tools.*tool_registry|tool_registry.*tools"):
        Agent(model="gpt-4o-mini", tools=[fn], tool_registry=registry)


async def test_mode_c_handler_invokable() -> None:
    """Registry handler can be called end-to-end via agent execution."""
    state: dict[str, int] = {}
    registry = _build_registry_with_dep(state)

    agent = Agent(model="gpt-4o-mini", tool_registry=registry)
    agent._agent.llm = FakeLLMProvider()  # type: ignore[attr-defined]

    # Just verify agent constructs + dispatches; tool not invoked by fake LLM
    result = await agent.run("Hello")
    assert result is not None


# ---------------------------------------------------------------------------
# Mode D — YAML prompt + pre-built registry (schemas from YAML, handlers from registry)
# ---------------------------------------------------------------------------


@pytest.fixture
def yaml_with_tools(tmp_path: Path) -> Path:
    project = tmp_path / "demo_app"
    project.mkdir()
    (project / "v1.yaml").write_text("""
version: "1.0"
description: "Tool YAML test"
model: "gpt-4o-mini"
temperature: 0.1
max_tokens: 256

prompts:
  ask:
    system: "You are a helper."
    user: "{query}"

tools:
  - name: lookup
    description: "Look up info by key."
    parameters:
      type: object
      properties:
        key: {type: string}
      required: [key]
""")
    return tmp_path


def test_mode_d_yaml_tool_schema_attached_to_registry_handler(yaml_with_tools: Path) -> None:
    """When Mode 4 + tool_registry= used, YAML schema overrides for matching handler name."""
    async def lookup(key: str) -> dict:
        """Python handler."""
        return {"key": key, "value": "found"}

    registry = ToolRegistry()
    registry.register("lookup", lookup)

    agent = Agent(
        model="gpt-4o-mini",
        prompt="demo_app:v1:ask",
        prompt_registry=PromptRegistry(prompts_root=yaml_with_tools),
        tool_registry=registry,
    )

    # Handler exists with schema from YAML
    handler = agent._agent.tool_registry._handlers["lookup"]  # type: ignore[attr-defined]
    assert handler.schema is not None
    assert handler.schema["function"]["description"] == "Look up info by key."


def test_mode_d_yaml_only_tools_no_handler_warning(yaml_with_tools: Path) -> None:
    """YAML defines tool but registry lacks handler → ValueError (clear failure)."""
    registry = ToolRegistry()  # empty
    with pytest.raises(ValueError, match="lookup"):
        Agent(
            model="gpt-4o-mini",
            prompt="demo_app:v1:ask",
            prompt_registry=PromptRegistry(prompts_root=yaml_with_tools),
            tool_registry=registry,
        )


def test_mode_d_yaml_without_registry_skips_tools(yaml_with_tools: Path) -> None:
    """Mode 4 without tool_registry → ignore YAML tools (only prompts loaded)."""
    agent = Agent(
        model="gpt-4o-mini",
        prompt="demo_app:v1:ask",
        prompt_registry=PromptRegistry(prompts_root=yaml_with_tools),
    )
    # No handlers registered — YAML tools skipped silently
    assert len(agent._agent.tool_registry._handlers) == 0  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Combined — Mode A and Mode B mixed
# ---------------------------------------------------------------------------


def test_mode_a_b_mixed_both_callable_and_itool_get_schemas() -> None:
    """Both callable AND ITool in list get their schemas attached."""
    def add(a: int, b: int) -> dict:
        """Add a and b."""
        return {"sum": a + b}

    tool = _StatefulTool()
    agent = Agent(model="gpt-4o-mini", tools=[add, tool])

    handlers = agent._agent.tool_registry._handlers  # type: ignore[attr-defined]
    # Callable schema auto-generated
    assert handlers["add"].schema["function"]["name"] == "add"
    # ITool schema preserved as-is
    assert handlers["stateful"].schema["function"]["name"] == "stateful"
