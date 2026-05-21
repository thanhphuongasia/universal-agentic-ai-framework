"""Tool schema auto-introspection from callable.

Phase 10 T2.4 — 6 cases. Expected RED until T4 implementation.
"""

from __future__ import annotations

import pytest

from ryuu.factory import Agent


def _get_tool_schema(agent: Agent, tool_name: str) -> dict:
    """Extract tool schema from agent's internal tool_registry."""
    handler = agent._agent.tool_registry._handlers[tool_name]  # type: ignore[attr-defined]
    return handler.schema


def test_schema_from_primitive_types(monkeypatch: pytest.MonkeyPatch) -> None:
    """str/int/float/bool primitives map to JSON Schema types."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    def my_tool(name: str, age: int, score: float, active: bool) -> dict:
        """Demo tool."""
        return {}

    agent = Agent(model="gpt-4o-mini", tools=[my_tool])
    schema = _get_tool_schema(agent, "my_tool")
    props = schema["function"]["parameters"]["properties"]
    assert props["name"]["type"] == "string"
    assert props["age"]["type"] == "integer"
    assert props["score"]["type"] == "number"
    assert props["active"]["type"] == "boolean"


def test_schema_from_container_types(monkeypatch: pytest.MonkeyPatch) -> None:
    """list/dict → array/object."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    def my_tool(tags: list, meta: dict) -> dict:
        """Demo tool."""
        return {}

    agent = Agent(model="gpt-4o-mini", tools=[my_tool])
    schema = _get_tool_schema(agent, "my_tool")
    props = schema["function"]["parameters"]["properties"]
    assert props["tags"]["type"] == "array"
    assert props["meta"]["type"] == "object"


def test_required_fields_no_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Params without default → required list."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    def my_tool(must: str, may: int = 0) -> dict:
        """Demo tool."""
        return {}

    agent = Agent(model="gpt-4o-mini", tools=[my_tool])
    schema = _get_tool_schema(agent, "my_tool")
    required = schema["function"]["parameters"]["required"]
    assert "must" in required
    assert "may" not in required


def test_description_from_docstring(monkeypatch: pytest.MonkeyPatch) -> None:
    """First line of docstring → tool description."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    def my_tool(x: int) -> int:
        """Compute the magic number.

        Longer explanation that should NOT appear in description.
        """
        return x * 42

    agent = Agent(model="gpt-4o-mini", tools=[my_tool])
    schema = _get_tool_schema(agent, "my_tool")
    desc = schema["function"]["description"]
    assert desc == "Compute the magic number."
    assert "Longer explanation" not in desc


def test_name_from_function_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tool name = fn.__name__."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    def get_weather_data(city: str) -> dict:
        """Get weather."""
        return {}

    agent = Agent(model="gpt-4o-mini", tools=[get_weather_data])
    schema = _get_tool_schema(agent, "get_weather_data")
    assert schema["function"]["name"] == "get_weather_data"


def test_no_docstring_empty_description(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tool without docstring → empty description (no crash)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    def my_tool(x: int) -> int:  # no docstring
        return x

    agent = Agent(model="gpt-4o-mini", tools=[my_tool])
    schema = _get_tool_schema(agent, "my_tool")
    assert schema["function"]["description"] == ""
