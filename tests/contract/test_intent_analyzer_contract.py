"""Contract tests for IIntentAnalyzer — P1-T09."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from uaaf._testing.fakes import FakeIntentAnalyzer, FakeLLMProvider
from uaaf.intent.models import StructuredIntent


def _make_fake_analyzer():
    return FakeIntentAnalyzer()


def _make_llm_analyzer():
    import json

    from uaaf.intent.models import DIRECT
    payload = json.dumps({
        "intent_type": "query",
        "action": "search",
        "entities": {},
        "complexity": "LOW",
        "confidence": 0.9,
        "ambiguous": False,
        "clarification_questions": [],
        "suggested_strategy": DIRECT,
        "suggested_model_tier": "standard",
    })
    from uaaf.providers.llm import Response, TokenUsage
    provider = FakeLLMProvider(responses=[
        Response(content=payload, model="fake", usage=TokenUsage(10, 5), finish_reason="stop"),
    ] * 20)
    from uaaf.intent.llm_analyzer import LLMIntentAnalyzer
    return LLMIntentAnalyzer(provider=provider)


ANALYZER_REGISTRY: dict[str, Callable] = {
    "fake": _make_fake_analyzer,
    "llm": _make_llm_analyzer,
}


@pytest.mark.parametrize("name,factory", ANALYZER_REGISTRY.items())
@pytest.mark.anyio
async def test_analyzer_returns_structured_intent(name: str, factory: Callable) -> None:
    analyzer = factory()
    result = await analyzer.analyze("test message", scope_key="u1:s1:test")
    assert isinstance(result, StructuredIntent)


@pytest.mark.parametrize("name,factory", ANALYZER_REGISTRY.items())
@pytest.mark.anyio
async def test_analyzer_result_has_intent_type(name: str, factory: Callable) -> None:
    analyzer = factory()
    result = await analyzer.analyze("test", scope_key="u1:s1:test")
    assert isinstance(result.intent_type, str)
    assert len(result.intent_type) > 0


@pytest.mark.parametrize("name,factory", ANALYZER_REGISTRY.items())
@pytest.mark.anyio
async def test_analyzer_result_confidence_in_range(name: str, factory: Callable) -> None:
    analyzer = factory()
    result = await analyzer.analyze("test", scope_key="u1:s1:test")
    assert 0.0 <= result.confidence <= 1.0


@pytest.mark.parametrize("name,factory", ANALYZER_REGISTRY.items())
@pytest.mark.anyio
async def test_analyzer_accepts_none_history(name: str, factory: Callable) -> None:
    analyzer = factory()
    result = await analyzer.analyze("test", scope_key="u1:s1:test", history=None)
    assert isinstance(result, StructuredIntent)


@pytest.mark.parametrize("name,factory", ANALYZER_REGISTRY.items())
@pytest.mark.anyio
async def test_analyzer_accepts_history_list(name: str, factory: Callable) -> None:
    analyzer = factory()
    history = [{"role": "user", "content": "previous"}, {"role": "assistant", "content": "reply"}]
    result = await analyzer.analyze("follow-up", scope_key="u1:s1:test", history=history)
    assert isinstance(result, StructuredIntent)
