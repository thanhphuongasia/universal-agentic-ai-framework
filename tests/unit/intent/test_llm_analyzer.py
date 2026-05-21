"""Tests for LLMIntentAnalyzer — P1-T07."""

from __future__ import annotations

import json

import pytest

from ryuu._testing.fakes import FakeLLMProvider
from ryuu.intent.llm_analyzer import LLMIntentAnalyzer
from ryuu.intent.models import DIRECT, REACT, ComplexityLevel, StructuredIntent
from ryuu.providers.llm import Response, TokenUsage


def _resp(content: str) -> Response:
    return Response(content=content, model="fake", usage=TokenUsage(10, 5), finish_reason="stop")


def _valid_json(
    intent_type: str = "query",
    action: str = "search",
    complexity: str = "LOW",
    confidence: float = 0.9,
    suggested_strategy: str = DIRECT,
) -> str:
    return json.dumps({
        "intent_type": intent_type,
        "action": action,
        "entities": {},
        "complexity": complexity,
        "confidence": confidence,
        "ambiguous": False,
        "clarification_questions": [],
        "suggested_strategy": suggested_strategy,
        "suggested_model_tier": "standard",
    })


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_llm_analyzer_parses_valid_json() -> None:
    provider = FakeLLMProvider(responses=[_resp(_valid_json())])
    analyzer = LLMIntentAnalyzer(provider=provider)
    intent = await analyzer.analyze("find all files", scope_key="u1:s1:test")

    assert isinstance(intent, StructuredIntent)
    assert intent.intent_type == "query"
    assert intent.action == "search"
    assert intent.complexity == ComplexityLevel.LOW
    assert intent.confidence == 0.9


@pytest.mark.anyio
async def test_llm_analyzer_maps_strategy_id() -> None:
    provider = FakeLLMProvider(responses=[_resp(_valid_json(suggested_strategy=REACT))])
    analyzer = LLMIntentAnalyzer(provider=provider)
    intent = await analyzer.analyze("analyze dependencies", scope_key="u1:s1:test")
    assert intent.suggested_strategy == REACT


@pytest.mark.anyio
async def test_llm_analyzer_passes_history_in_prompt() -> None:
    provider = FakeLLMProvider(responses=[_resp(_valid_json())])
    analyzer = LLMIntentAnalyzer(provider=provider)
    history = [{"role": "user", "content": "prev msg"}]
    await analyzer.analyze("new message", scope_key="u1:s1:test", history=history)
    assert provider.call_count == 1
    assert provider.last_request is not None


# ---------------------------------------------------------------------------
# Fallback on parse error
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_llm_analyzer_fallback_on_invalid_json() -> None:
    provider = FakeLLMProvider(responses=[_resp("not json at all")])
    analyzer = LLMIntentAnalyzer(provider=provider)
    intent = await analyzer.analyze("something", scope_key="u1:s1:test")

    assert intent.ambiguous is True
    assert len(intent.clarification_questions) > 0
    assert intent.confidence < 0.5


@pytest.mark.anyio
async def test_llm_analyzer_fallback_on_missing_fields() -> None:
    provider = FakeLLMProvider(responses=[_resp('{"intent_type": "query"}')])
    analyzer = LLMIntentAnalyzer(provider=provider)
    intent = await analyzer.analyze("something", scope_key="u1:s1:test")

    assert intent.ambiguous is True


@pytest.mark.anyio
async def test_llm_analyzer_extracts_json_from_prose() -> None:
    """LLM sometimes wraps JSON in markdown code blocks."""
    payload = _valid_json(intent_type="analysis", complexity="HIGH")
    provider = FakeLLMProvider(responses=[_resp(f"Here is the intent:\n```json\n{payload}\n```")])
    analyzer = LLMIntentAnalyzer(provider=provider)
    intent = await analyzer.analyze("complex query", scope_key="u1:s1:test")

    assert intent.intent_type == "analysis"
    assert intent.complexity == ComplexityLevel.HIGH
