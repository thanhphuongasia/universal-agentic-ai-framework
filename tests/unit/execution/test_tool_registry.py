"""Tests for uaaf.execution.tool_registry — ITool Protocol + ToolRegistry."""

from __future__ import annotations

import json
import pytest
from typing import Any

from uaaf.execution.tool_registry import ITool, ToolRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_tool_call(name: str, args: dict[str, Any], call_id: str = "call_1") -> dict[str, Any]:
    return {"id": call_id, "function": {"name": name, "arguments": args}}


class EchoTool:
    """Concrete ITool that echoes its args."""
    tool_id = "echo"
    schema: dict[str, Any] | None = None

    async def execute(self, args: dict[str, Any]) -> Any:
        return {"echoed": args}


class FailTool:
    """Concrete ITool that always raises."""
    tool_id = "fail"
    schema: dict[str, Any] | None = None

    async def execute(self, args: dict[str, Any]) -> Any:
        raise ValueError("intentional failure")


# ---------------------------------------------------------------------------
# ITool Protocol structural check
# ---------------------------------------------------------------------------

def test_echo_tool_satisfies_itool_protocol() -> None:
    """EchoTool has all required ITool attributes."""
    tool = EchoTool()
    assert hasattr(tool, "tool_id")
    assert hasattr(tool, "schema")
    assert hasattr(tool, "execute")
    assert isinstance(tool, ITool)


# ---------------------------------------------------------------------------
# ToolRegistry — register and run (no domain restriction)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_registry_run_itool() -> None:
    reg = ToolRegistry()
    reg.register("echo", EchoTool())
    result = await reg.run(make_tool_call("echo", {"x": 1}))
    data = json.loads(result)
    assert data == {"echoed": {"x": 1}}


@pytest.mark.anyio
async def test_registry_run_callable_handler() -> None:
    """Callable (lambda) handlers registered without domain restriction still work."""
    reg = ToolRegistry()

    async def add(a: int, b: int) -> int:
        return a + b

    reg.register("add", add)
    result = await reg.run(make_tool_call("add", {"a": 2, "b": 3}))
    assert json.loads(result) == 5


@pytest.mark.anyio
async def test_registry_unknown_tool_returns_error_json() -> None:
    reg = ToolRegistry()
    result = await reg.run(make_tool_call("nonexistent", {}))
    data = json.loads(result)
    assert "error" in data
    assert "nonexistent" in data["error"]


# ---------------------------------------------------------------------------
# ToolRegistry — domain whitelist
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_registry_allowed_domain_passes() -> None:
    reg = ToolRegistry()
    reg.register("echo", EchoTool(), allowed_domains={"todo", "stock"})
    result = await reg.run(make_tool_call("echo", {"k": "v"}), domain="todo")
    assert json.loads(result) == {"echoed": {"k": "v"}}


@pytest.mark.anyio
async def test_registry_disallowed_domain_raises_permission_error() -> None:
    reg = ToolRegistry()
    reg.register("echo", EchoTool(), allowed_domains={"stock"})
    with pytest.raises(PermissionError, match="echo"):
        await reg.run(make_tool_call("echo", {}), domain="todo")


@pytest.mark.anyio
async def test_registry_none_allowed_domains_permits_any_domain() -> None:
    """allowed_domains=None means all domains are permitted."""
    reg = ToolRegistry()
    reg.register("echo", EchoTool(), allowed_domains=None)
    result = await reg.run(make_tool_call("echo", {"x": 99}), domain="any_domain")
    assert json.loads(result) == {"echoed": {"x": 99}}


@pytest.mark.anyio
async def test_registry_default_register_permits_any_domain() -> None:
    """Registering without allowed_domains defaults to None (all domains OK)."""
    reg = ToolRegistry()
    reg.register("echo", EchoTool())
    result = await reg.run(make_tool_call("echo", {}), domain="random")
    assert "echoed" in json.loads(result)


# ---------------------------------------------------------------------------
# ToolRegistry — run_all
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_run_all_returns_list_with_tool_call_ids() -> None:
    reg = ToolRegistry()
    reg.register("echo", EchoTool())

    calls = [
        make_tool_call("echo", {"n": 1}, call_id="c1"),
        make_tool_call("echo", {"n": 2}, call_id="c2"),
    ]
    results = await reg.run_all(calls)
    assert len(results) == 2
    assert results[0]["tool_call_id"] == "c1"
    assert results[1]["tool_call_id"] == "c2"
    assert json.loads(results[0]["content"]) == {"echoed": {"n": 1}}
    assert json.loads(results[1]["content"]) == {"echoed": {"n": 2}}


@pytest.mark.anyio
async def test_run_all_with_domain_filter() -> None:
    reg = ToolRegistry()
    reg.register("echo", EchoTool(), allowed_domains={"todo"})
    calls = [make_tool_call("echo", {"x": 0}, call_id="id1")]
    results = await reg.run_all(calls, domain="todo")
    assert results[0]["tool_call_id"] == "id1"


@pytest.mark.anyio
async def test_run_all_domain_violation_raises() -> None:
    reg = ToolRegistry()
    reg.register("echo", EchoTool(), allowed_domains={"stock"})
    calls = [make_tool_call("echo", {}, call_id="x")]
    with pytest.raises(PermissionError):
        await reg.run_all(calls, domain="todo")


# ---------------------------------------------------------------------------
# ToolRegistry — handlers field exposed for LLMAgent introspection
# ---------------------------------------------------------------------------

def test_registry_handlers_dict_accessible() -> None:
    """LLMAgent checks bool(registry._handlers) to skip tool passing when empty."""
    reg = ToolRegistry()
    assert not reg._handlers
    reg.register("echo", EchoTool())
    assert "echo" in reg._handlers
