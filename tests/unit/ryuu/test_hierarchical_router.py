"""Phase 14.4 — HierarchicalRouter facade tests (Layer B — routing).

5 cases. 2-stage routing: category → specific intent within category.
"""

from __future__ import annotations

import pytest

from ryuu import Agent, HierarchicalRouter
from ryuu._testing.fakes import FakeLLMProvider
from ryuu.providers.llm import Response, TokenUsage


def _fake(text: str) -> Response:
    return Response(
        content=text, model="fake",
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        finish_reason="stop",
    )


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")


def _attach(agent: Agent, responses: list[str]) -> Agent:
    agent._agent.llm = FakeLLMProvider(responses=[_fake(r) for r in responses])
    return agent


async def test_hierarchical_router_2_stage_dispatch() -> None:
    """Stage 1 picks category 'data', Stage 2 picks specific intent."""
    cat = _attach(
        Agent(model="gpt-4o-mini", instructions="Pick category"),
        ["data"],
    )
    crud_agent = _attach(
        Agent(model="gpt-4o-mini", instructions="CRUD handler"),
        ["[crud_matrix result]"],
    )
    specific_picker_response = ["crud_matrix"]

    # Mock specific_analyzer that always returns crud_matrix
    router = HierarchicalRouter(
        category_classifier=cat,
        routes_by_category={
            "data":      {"crud_matrix": crud_agent, "entity_diagram": crud_agent},
            "structure": {"symbol_explain": crud_agent},
        },
        specific_analyzer=lambda q, opts: "crud_matrix",
    )
    result = await router.run("Show CRUD for User")
    assert "[crud_matrix result]" in str(result)


async def test_hierarchical_router_fallback_route() -> None:
    """Unknown category → fallback_route used."""
    cat = _attach(
        Agent(model="gpt-4o-mini", instructions="cat"),
        ["unknown_category"],
    )
    fallback_agent = _attach(
        Agent(model="gpt-4o-mini", instructions="default"),
        ["[fallback result]"],
    )
    router = HierarchicalRouter(
        category_classifier=cat,
        routes_by_category={"data": {"crud_matrix": fallback_agent}},
        fallback_route=fallback_agent,
        specific_analyzer=lambda q, opts: opts[0],
    )
    result = await router.run("query")
    assert "[fallback result]" in str(result)


async def test_hierarchical_router_unknown_category_no_fallback_raises() -> None:
    """Unknown category + no fallback → KeyError."""
    cat = _attach(
        Agent(model="gpt-4o-mini", instructions="cat"),
        ["nonexistent"],
    )
    router = HierarchicalRouter(
        category_classifier=cat,
        routes_by_category={"data": {"crud_matrix": cat}},
        # no fallback_route
    )
    with pytest.raises(KeyError, match="nonexistent"):
        await router.run("query")


async def test_hierarchical_router_default_llm_specific_picker() -> None:
    """Without specific_analyzer, default LLM classifier picks from options."""
    cat = _attach(
        Agent(model="gpt-4o-mini", instructions="cat"),
        ["data"],
    )
    # Specific picker uses LLM internally — pre-stage response
    crud_agent = _attach(
        Agent(model="gpt-4o-mini", instructions="crud"),
        ["crud_matrix", "[crud result]"],   # 1st = picker output, 2nd = agent output
    )
    router = HierarchicalRouter(
        category_classifier=cat,
        routes_by_category={
            "data": {"crud_matrix": crud_agent, "entity_diagram": crud_agent},
        },
    )
    result = await router.run("query")
    assert "crud" in str(result).lower()


async def test_hierarchical_router_validation_empty_routes() -> None:
    """Empty routes_by_category → ValueError."""
    cat = _attach(Agent(model="gpt-4o-mini", instructions="x"), ["x"])
    with pytest.raises(ValueError, match="routes_by_category"):
        HierarchicalRouter(
            category_classifier=cat,
            routes_by_category={},
        )
