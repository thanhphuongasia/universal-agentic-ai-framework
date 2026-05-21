"""Phase 13 — PromptOptimizer tests.

8 cases: optimize loop, score function, variant generation, history tracking,
LLM-based variant generator with FakeLLMProvider.
"""

from __future__ import annotations

import pytest

from ryuu import Agent
from ryuu._testing.fakes import FakeLLMProvider
from ryuu.prompt_optimizer import EvalCase, OptimizationResult, PromptOptimizer
from ryuu.providers.llm import Response, TokenUsage


def _fake(text: str = "ok") -> Response:
    return Response(
        content=text, model="fake",
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        finish_reason="stop",
    )


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")


def _exact_match(output: str, expected: str) -> float:
    return 1.0 if output.strip() == expected else 0.0


def _contains(output: str, expected: str) -> float:
    return 1.0 if expected.lower() in output.lower() else 0.0


# ── Basic optimize loop ─────────────────────────────────────────────────────


async def test_optimize_returns_best_prompt() -> None:
    """Optimizer picks variant with highest aggregate score."""
    cases = [
        EvalCase(input="q1", expected="good"),
        EvalCase(input="q2", expected="good"),
    ]

    # Variant generator: alternate "bad" and "good" replies
    def gen_variants(current: str) -> list[str]:
        return ["BAD_PROMPT", "GOOD_PROMPT"]

    # Agent reply depends on prompt: returns "good" only when GOOD_PROMPT used
    call_count = {"n": 0}

    async def fake_score(output: str, expected: str) -> float:
        # First variants get bad reply, second get good (deterministic-ish)
        call_count["n"] += 1
        return _contains(output, expected)

    base = Agent(model="gpt-4o-mini", instructions="initial")
    # Provide enough responses for all variant evaluations
    base._agent.llm = FakeLLMProvider(responses=[  # type: ignore[attr-defined]
        _fake("bad"), _fake("good"),    # base eval (2 cases)
        _fake("bad"), _fake("bad"),     # variant 1 (BAD_PROMPT, 2 cases)
        _fake("good"), _fake("good"),   # variant 2 (GOOD_PROMPT, 2 cases)
    ])

    optimizer = PromptOptimizer(
        base_agent=base,
        eval_cases=cases,
        score_fn=_contains,
        variant_generator=gen_variants,
        max_rounds=1,
    )
    result = await optimizer.optimize()
    assert isinstance(result, OptimizationResult)
    assert result.best_prompt == "GOOD_PROMPT"
    assert result.best_score == 1.0   # 2/2 cases pass


async def test_optimize_returns_base_if_no_variant_better() -> None:
    """If all variants score ≤ base, base prompt wins."""
    cases = [EvalCase(input="q1", expected="x")]

    def gen_variants(current: str) -> list[str]:
        return ["worse1", "worse2"]

    base = Agent(model="gpt-4o-mini", instructions="base_prompt")
    base._agent.llm = FakeLLMProvider(responses=[  # type: ignore[attr-defined]
        _fake("x"), _fake(""), _fake(""),
    ])

    optimizer = PromptOptimizer(
        base_agent=base,
        eval_cases=cases,
        score_fn=_contains,
        variant_generator=gen_variants,
        max_rounds=1,
    )
    result = await optimizer.optimize()
    assert result.best_prompt == "base_prompt"
    assert result.best_score == 1.0


async def test_optimize_history_tracks_rounds() -> None:
    """`history` list has one entry per round + base."""
    cases = [EvalCase(input="q", expected="ans")]

    def gen(_: str) -> list[str]:
        return ["v1"]

    base = Agent(model="gpt-4o-mini", instructions="b")
    base._agent.llm = FakeLLMProvider(responses=[  # type: ignore[attr-defined]
        _fake("") for _ in range(20)
    ])

    optimizer = PromptOptimizer(
        base_agent=base, eval_cases=cases, score_fn=_exact_match,
        variant_generator=gen, max_rounds=3,
    )
    result = await optimizer.optimize()
    # 1 base + 3 rounds, each round had 1 variant = 4 evaluations tracked
    assert len(result.history) >= 4


async def test_optimize_max_rounds_respected() -> None:
    """Optimizer stops after max_rounds iterations."""
    cases = [EvalCase(input="q", expected="x")]
    call_count = {"n": 0}

    def gen(_: str) -> list[str]:
        call_count["n"] += 1
        return ["v"]

    base = Agent(model="gpt-4o-mini", instructions="b")
    base._agent.llm = FakeLLMProvider(responses=[  # type: ignore[attr-defined]
        _fake("") for _ in range(20)
    ])

    optimizer = PromptOptimizer(
        base_agent=base, eval_cases=cases, score_fn=_exact_match,
        variant_generator=gen, max_rounds=2,
    )
    await optimizer.optimize()
    assert call_count["n"] == 2   # 2 rounds, generator called once per round


async def test_optimize_variants_per_round() -> None:
    """Variant generator returns N variants → N evaluations per round."""
    cases = [EvalCase(input="q", expected="x")]
    eval_counts = {"n": 0}

    def gen(_: str) -> list[str]:
        return ["v1", "v2", "v3"]

    async def counting_score(output: str, expected: str) -> float:
        eval_counts["n"] += 1
        return 0.0

    base = Agent(model="gpt-4o-mini", instructions="b")
    base._agent.llm = FakeLLMProvider(responses=[  # type: ignore[attr-defined]
        _fake("") for _ in range(20)
    ])

    optimizer = PromptOptimizer(
        base_agent=base, eval_cases=cases, score_fn=counting_score,
        variant_generator=gen, max_rounds=1,
    )
    await optimizer.optimize()
    # base (1 case) + 3 variants × 1 case = 4 evaluations
    assert eval_counts["n"] == 4


# ── Validation ─────────────────────────────────────────────────────────────


def test_optimize_validation_empty_cases() -> None:
    """No eval_cases → ValueError."""
    with pytest.raises(ValueError, match="eval_cases"):
        PromptOptimizer(
            base_agent=Agent(model="gpt-4o-mini", instructions="b"),
            eval_cases=[],
            score_fn=_exact_match,
            variant_generator=lambda p: ["x"],
        )


def test_optimize_validation_negative_rounds() -> None:
    """max_rounds < 1 → ValueError."""
    with pytest.raises(ValueError, match="max_rounds"):
        PromptOptimizer(
            base_agent=Agent(model="gpt-4o-mini", instructions="b"),
            eval_cases=[EvalCase(input="q", expected="x")],
            score_fn=_exact_match,
            variant_generator=lambda p: ["x"],
            max_rounds=0,
        )


# ── Built-in LLM variant generator ─────────────────────────────────────────


async def test_llm_variant_generator() -> None:
    """Built-in llm_variant_generator uses LLM to paraphrase prompts."""
    from ryuu.prompt_optimizer import llm_variant_generator

    # FakeLLMProvider returns 3 paraphrased variants (newline-separated)
    fake_llm = FakeLLMProvider(responses=[
        _fake("Variant 1: be concise\nVariant 2: be detailed\nVariant 3: use steps"),
    ])

    gen = llm_variant_generator(provider=fake_llm, n_variants=3)
    variants = await gen("Original prompt")
    assert len(variants) >= 1   # at least one variant extracted
