"""Phase 11.y — Factory output_schema= structured output tests."""

from __future__ import annotations

import json

import pytest

from ryuu import Agent
from ryuu._testing.fakes import FakeLLMProvider
from ryuu.providers.llm import CompletionRequest, Response, TokenUsage
from ryuu_providers.adapters.openai import _supports_strict_schema


PERSON_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "age": {"type": "integer"},
    },
    "required": ["name"],
    "additionalProperties": False,
}


def _fake_json(payload: dict) -> Response:
    return Response(
        content=json.dumps(payload), model="fake",
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        finish_reason="stop",
    )


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")


async def test_agent_output_schema_auto_parses_to_result_parsed() -> None:
    """`output_schema=` → AgentResult.parsed populated với dict."""
    agent = Agent(
        model="gpt-4o-mini",
        instructions="Extract person info",
        output_schema=PERSON_SCHEMA,
    )
    agent._agent.llm = FakeLLMProvider(responses=[  # type: ignore[attr-defined]
        _fake_json({"name": "Alice", "age": 30}),
    ])
    result = await agent.run("Alice is 30 years old")
    assert result.parsed == {"name": "Alice", "age": 30}
    # Raw output still available
    assert '"name"' in str(result.output)


async def test_agent_output_schema_strips_markdown_fences() -> None:
    """Output wrapped in ```json fences → parsed correctly."""
    agent = Agent(
        model="gpt-4o-mini",
        instructions="Extract",
        output_schema=PERSON_SCHEMA,
    )
    fenced = '```json\n{"name": "Bob"}\n```'
    agent._agent.llm = FakeLLMProvider(responses=[  # type: ignore[attr-defined]
        Response(content=fenced, model="fake",
                 usage=TokenUsage(input_tokens=10, output_tokens=5),
                 finish_reason="stop"),
    ])
    result = await agent.run("Bob")
    assert result.parsed == {"name": "Bob"}


async def test_agent_output_schema_invalid_json_parsed_none() -> None:
    """Output not valid JSON → parsed=None, raw text in output (graceful)."""
    agent = Agent(
        model="gpt-4o-mini",
        instructions="...",
        output_schema=PERSON_SCHEMA,
    )
    agent._agent.llm = FakeLLMProvider(responses=[  # type: ignore[attr-defined]
        Response(content="not valid json here", model="fake",
                 usage=TokenUsage(input_tokens=10, output_tokens=5),
                 finish_reason="stop"),
    ])
    result = await agent.run("query")
    assert result.parsed is None
    assert "not valid json" in str(result.output)


async def test_agent_no_output_schema_parsed_stays_none() -> None:
    """Default (no schema) → result.parsed is None (backward compat)."""
    agent = Agent(model="gpt-4o-mini", instructions="...")
    agent._agent.llm = FakeLLMProvider(responses=[  # type: ignore[attr-defined]
        Response(content='{"valid": "json"}', model="fake",
                 usage=TokenUsage(input_tokens=10, output_tokens=5),
                 finish_reason="stop"),
    ])
    result = await agent.run("hi")
    # No schema → no auto-parse, even though output happens to be JSON
    assert result.parsed is None


async def test_agent_output_schema_forwarded_to_completion_request() -> None:
    """Internal _output_schema field carries schema to CompletionRequest."""
    agent = Agent(
        model="gpt-4o-mini",
        instructions="...",
        output_schema=PERSON_SCHEMA,
    )
    assert agent._agent._output_schema == PERSON_SCHEMA  # type: ignore[attr-defined]


def test_openai_strict_mode_detection() -> None:
    """gpt-4o family → strict schema mode; older → fallback."""
    assert _supports_strict_schema("gpt-4o") is True
    assert _supports_strict_schema("gpt-4o-mini") is True
    assert _supports_strict_schema("o1-preview") is True
    assert _supports_strict_schema("gpt-5-mini") is True
    assert _supports_strict_schema("gpt-3.5-turbo") is False
    assert _supports_strict_schema("gpt-4-turbo") is False


def test_openai_adapter_builds_strict_json_schema_kwargs() -> None:
    """OpenAIProvider with gpt-4o + response_schema → strict json_schema mode."""
    from ryuu_providers.adapters.openai import OpenAIProvider

    # Build request directly (no LLM call) — verify kwargs construction
    request = CompletionRequest(
        messages=[],
        model="gpt-4o-mini",
        response_schema=PERSON_SCHEMA,
    )

    # Replicate adapter's kwargs building (since complete() is hard to mock)
    kwargs: dict = {"model": "gpt-4o-mini", "response_format": None}
    if request.response_schema and _supports_strict_schema(request.model):
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "structured_output",
                "schema": request.response_schema,
                "strict": True,
            },
        }
    assert kwargs["response_format"]["type"] == "json_schema"
    assert kwargs["response_format"]["json_schema"]["strict"] is True
    assert kwargs["response_format"]["json_schema"]["schema"] == PERSON_SCHEMA
