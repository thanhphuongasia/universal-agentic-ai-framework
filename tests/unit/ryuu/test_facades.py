"""Phase 10.5: Multi-agent facades — Chain / FanOut / Router / Orchestrator / Evaluator.

~25 cases (5 per facade). Each facade implements `.run(input) → output` uniformly,
allowing nesting / composition.

Each test uses FakeLLMProvider to make the agent deterministic — focus on facade
plumbing, not LLM behavior.
"""

from __future__ import annotations

import pytest

from ryuu import Agent
from ryuu._testing.fakes import FakeLLMProvider
from ryuu.facades import Chain, Evaluator, FanOut, Orchestrator, Router
from ryuu.providers.llm import Response, TokenUsage


def _fake_response(text: str = "ok") -> Response:
    return Response(
        content=text,
        model="fake",
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        finish_reason="stop",
    )


def _make_agent(reply: str = "ok") -> Agent:
    a = Agent(model="gpt-4o-mini")
    a._agent.llm = FakeLLMProvider(responses=[_fake_response(reply)])  # type: ignore[attr-defined]
    return a


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")


# ── Chain ──────────────────────────────────────────────────────────────────


async def test_chain_passes_output_through_agents() -> None:
    """Chain of 2 agents: output of A → input of B."""
    chain = Chain([_make_agent("step1"), _make_agent("step2")])
    result = await chain.run("input")
    # Last agent's output is the final result
    assert result == "step2"


async def test_chain_accepts_callable_transform() -> None:
    """Chain accepts callable transform between agents."""
    chain = Chain([_make_agent("hello"), str.upper])
    result = await chain.run("anything")
    assert result == "HELLO"


async def test_chain_empty_raises() -> None:
    """Empty chain → ValueError."""
    with pytest.raises(ValueError, match="empty"):
        Chain([])


# ── FanOut ─────────────────────────────────────────────────────────────────


async def test_fanout_variant_1_data_items() -> None:
    """Variant 1: 1 agent + N items → N results."""
    agent = _make_agent("processed")
    # Build a new FakeLLMProvider with 3 responses (one per item)
    agent._agent.llm = FakeLLMProvider(responses=[  # type: ignore[attr-defined]
        _fake_response("r1"), _fake_response("r2"), _fake_response("r3"),
    ])
    fan = FanOut(agent=agent, items=["a", "b", "c"], template="{item}")
    results = await fan.run()
    assert len(results) == 3


async def test_fanout_variant_2_agents() -> None:
    """Variant 2: N agents, same input."""
    fan = FanOut(agents=[_make_agent("a"), _make_agent("b"), _make_agent("c")])
    results = await fan.run("same input")
    assert len(results) == 3


async def test_fanout_validation_exactly_one_mode() -> None:
    """Setting both `items` and `agents` → ValueError."""
    with pytest.raises(ValueError, match="exactly one"):
        FanOut(agent=_make_agent(), items=["x"], agents=[_make_agent()])


# ── Router ─────────────────────────────────────────────────────────────────


async def test_router_dispatches_via_analyzer() -> None:
    """Router(analyzer) picks route based on analyzer output."""
    router = Router(
        routes={"a": _make_agent("from_a"), "b": _make_agent("from_b")},
        analyzer=lambda q: "a" if "alpha" in q else "b",
    )
    assert await router.run("alpha") == "from_a"
    # Need to recreate fakes for second call
    router = Router(
        routes={"a": _make_agent("from_a"), "b": _make_agent("from_b")},
        analyzer=lambda q: "a" if "alpha" in q else "b",
    )
    assert await router.run("beta") == "from_b"


async def test_router_default_route() -> None:
    """`_default` route used when analyzer returns unknown key."""
    router = Router(
        routes={"a": _make_agent("from_a"), "_default": _make_agent("fallback")},
        analyzer=lambda q: "unknown_key",
    )
    assert await router.run("xyz") == "fallback"


def test_router_validation_no_routes() -> None:
    """Empty routes → ValueError."""
    with pytest.raises(ValueError, match="routes"):
        Router(routes={}, analyzer=lambda q: "x")


# ── Orchestrator ───────────────────────────────────────────────────────────


async def test_orchestrator_main_spawns_workers() -> None:
    """Main agent generates list, workers spawn per item."""
    main = _make_agent("plan: [a, b, c]")

    def worker_factory(item: str) -> Agent:
        return _make_agent(f"worked-{item}")

    orch = Orchestrator(
        main=main,
        workers=worker_factory,
        plan_items=lambda main_output: ["a", "b", "c"],   # extract from main output
        aggregate=lambda outputs: ",".join(outputs),
    )
    result = await orch.run("input")
    assert "worked-a" in result and "worked-c" in result


async def test_orchestrator_aggregate_combines_worker_outputs() -> None:
    """`aggregate` callable combines worker outputs into final result."""
    main = _make_agent("done")

    def worker(item: str) -> Agent:
        return _make_agent(f"w-{item}")

    orch = Orchestrator(
        main=main,
        workers=worker,
        plan_items=lambda _out: ["x"],
        aggregate=lambda outputs: outputs[0].upper(),
    )
    assert await orch.run("anything") == "W-X"


# ── Evaluator ──────────────────────────────────────────────────────────────


async def test_evaluator_passes_on_first_try() -> None:
    """Generator output valid → return immediately, no refine."""
    gen = _make_agent("valid result")
    evaluator = Evaluator(
        generator=gen,
        verifier=lambda output: (True, ""),   # always passes
        max_refines=2,
    )
    result = await evaluator.run("input")
    assert result == "valid result"


async def test_evaluator_refines_on_failure() -> None:
    """Generator fails verify → refine + retry, return refined output."""
    gen = Agent(model="gpt-4o-mini")
    # Two responses: first fails verify, second passes
    gen._agent.llm = FakeLLMProvider(responses=[  # type: ignore[attr-defined]
        _fake_response("bad"), _fake_response("refined"),
    ])

    call_count = {"n": 0}

    def verifier(output: str) -> tuple[bool, str]:
        call_count["n"] += 1
        return (output == "refined", "be better")

    evaluator = Evaluator(generator=gen, verifier=verifier, max_refines=2)
    result = await evaluator.run("input")
    assert result == "refined"
    assert call_count["n"] == 2


async def test_evaluator_max_refines_exhausted_returns_last() -> None:
    """All refine attempts fail → return last output."""
    gen = Agent(model="gpt-4o-mini")
    gen._agent.llm = FakeLLMProvider(responses=[  # type: ignore[attr-defined]
        _fake_response("attempt1"), _fake_response("attempt2"), _fake_response("attempt3"),
    ])

    evaluator = Evaluator(
        generator=gen,
        verifier=lambda out: (False, "still bad"),
        max_refines=2,
    )
    result = await evaluator.run("input")
    # Last attempt's output returned (best-effort)
    assert "attempt" in result


def test_evaluator_validation_max_refines_negative() -> None:
    """max_refines < 0 → ValueError."""
    with pytest.raises(ValueError, match="max_refines"):
        Evaluator(generator=_make_agent(), verifier=lambda o: (True, ""), max_refines=-1)


# ── Composability — facades nest into Chain ─────────────────────────────────


async def test_facades_compose_chain_of_router() -> None:
    """Chain contains a Router (nesting works)."""
    inner = Router(routes={"_default": _make_agent("routed")}, analyzer=lambda q: "_default")
    chain = Chain([inner, str.upper])
    assert await chain.run("input") == "ROUTED"
