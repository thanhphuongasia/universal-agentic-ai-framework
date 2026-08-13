"""Tests for LLMJudge and related scorers in ryuu-eval-scorers."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from ryuu_eval_core.models import EvalCase
from ryuu_eval_scorers import (
    Contains,
    ExactMatch,
    Regex,
    LLMJudge,
    SemanticSimilarity,
    Composite,
)
from ryuu_eval_scorers.scorers import _parse_judge_response, _render_template


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_case(input: str = "Q", expected: str | None = "A") -> EvalCase:
    return EvalCase(case_id="t1", input=input, expected=expected)


def make_provider(response_content: str) -> MagicMock:
    """Return a mock provider whose complete() returns a response with given content."""
    resp = MagicMock()
    resp.content = response_content
    provider = MagicMock()
    provider.complete = AsyncMock(return_value=resp)
    return provider


# ---------------------------------------------------------------------------
# ExactMatch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exact_match_pass():
    r = await ExactMatch().score(make_case(expected="hello"), "hello")
    assert r.passed and r.score == 1.0


@pytest.mark.asyncio
async def test_exact_match_fail():
    r = await ExactMatch().score(make_case(expected="hello"), "world")
    assert not r.passed and r.score == 0.0


@pytest.mark.asyncio
async def test_exact_match_strips_whitespace():
    r = await ExactMatch().score(make_case(expected=" hi "), "hi")
    assert r.passed


# ---------------------------------------------------------------------------
# Contains
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_contains_single_pass():
    r = await Contains("Paris").score(make_case(), "Paris is in France")
    assert r.passed and r.score == 1.0


@pytest.mark.asyncio
async def test_contains_case_insensitive_default():
    r = await Contains("paris").score(make_case(), "PARIS is a city")
    assert r.passed


@pytest.mark.asyncio
async def test_contains_multiple_all_present():
    r = await Contains(["Paris", "France"]).score(make_case(), "Paris is in France")
    assert r.passed and r.score == 1.0


@pytest.mark.asyncio
async def test_contains_multiple_partial():
    r = await Contains(["Paris", "Berlin"]).score(make_case(), "Paris is in France")
    assert not r.passed
    assert r.score == 0.5
    assert "Berlin" in r.reason


@pytest.mark.asyncio
async def test_contains_case_sensitive_fail():
    r = await Contains(["paris"], case_sensitive=True).score(make_case(), "PARIS")
    assert not r.passed


# ---------------------------------------------------------------------------
# Regex
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_regex_search_pass():
    r = await Regex(r"\d{4}-\d{2}-\d{2}").score(make_case(), "Date: 2024-01-15")
    assert r.passed


@pytest.mark.asyncio
async def test_regex_search_fail():
    r = await Regex(r"\d{4}-\d{2}-\d{2}").score(make_case(), "no date here")
    assert not r.passed


@pytest.mark.asyncio
async def test_regex_fullmatch_pass():
    r = await Regex(r"\d+", mode="fullmatch").score(make_case(), "12345")
    assert r.passed


@pytest.mark.asyncio
async def test_regex_fullmatch_fail():
    r = await Regex(r"\d+", mode="fullmatch").score(make_case(), "abc123")
    assert not r.passed


# ---------------------------------------------------------------------------
# _parse_judge_response
# ---------------------------------------------------------------------------

def test_parse_clean_json():
    text = '{"score": 0.85, "passed": true, "reason": "looks good"}'
    score, passed, reason = _parse_judge_response(text, 0.7)
    assert score == 0.85
    assert passed is True
    assert reason == "looks good"


def test_parse_json_with_markdown_fences():
    text = '```json\n{"score": 0.5, "passed": false, "reason": "incomplete"}\n```'
    score, passed, _ = _parse_judge_response(text, 0.7)
    assert score == 0.5
    assert passed is False


def test_parse_score_clamps_to_range():
    text = '{"score": 1.5, "passed": true, "reason": ""}'
    score, _, _ = _parse_judge_response(text, 0.7)
    assert score == 1.0

    text2 = '{"score": -0.3, "passed": false, "reason": ""}'
    score2, _, _ = _parse_judge_response(text2, 0.7)
    assert score2 == 0.0


def test_parse_regex_fallback():
    text = 'score: 0.75 — this output is partially correct'
    score, passed, _ = _parse_judge_response(text, 0.7)
    assert score == 0.75
    assert passed is True


def test_parse_keyword_pass_fallback():
    score, passed, _ = _parse_judge_response("This clearly passes.", 0.7)
    assert passed is True and score == 1.0


def test_parse_keyword_fail_fallback():
    score, passed, _ = _parse_judge_response("This output fails the check.", 0.7)
    assert passed is False and score == 0.0


def test_parse_unparseable_returns_zero():
    score, passed, reason = _parse_judge_response("blah blah nothing useful", 0.7)
    assert score == 0.0
    assert passed is False
    assert "unparseable" in reason


# ---------------------------------------------------------------------------
# _render_template
# ---------------------------------------------------------------------------

def test_render_template_fills_placeholders():
    tmpl = "Input: {{input}}\nOutput: {{output}}\nExpected: {{expected}}"
    result = _render_template(tmpl, "question", "answer", "ref")
    assert "question" in result
    assert "answer" in result
    assert "ref" in result


def test_render_template_removes_jinja_blocks():
    tmpl = "Output: {{output}}\n{% if expected %}Ref: {{expected}}{% endif %}"
    result = _render_template(tmpl, "q", "a", None)
    assert "{%" not in result


# ---------------------------------------------------------------------------
# LLMJudge — single criterion
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_judge_single_criterion_pass():
    provider = make_provider('{"score": 0.9, "passed": true, "reason": "accurate"}')
    scorer = LLMJudge(provider, criteria="factuality", threshold=0.7)
    result = await scorer.score(make_case(), "The answer is correct.")
    assert result.passed
    assert result.score == 0.9
    assert result.scorer_id == "llm-judge:factuality"
    provider.complete.assert_called_once()


@pytest.mark.asyncio
async def test_llm_judge_single_criterion_fail():
    provider = make_provider('{"score": 0.4, "passed": false, "reason": "hallucinated"}')
    scorer = LLMJudge(provider, criteria="factuality")
    result = await scorer.score(make_case(), "Wrong answer.")
    assert not result.passed
    assert result.score == 0.4


@pytest.mark.asyncio
async def test_llm_judge_custom_prompt():
    provider = make_provider('{"score": 1.0, "passed": true, "reason": "ok"}')
    scorer = LLMJudge(
        provider,
        criteria="custom",
        prompt_template="Check: {{output}}\nReturn JSON: {\"score\": 1.0, \"passed\": true, \"reason\": \"\"}",
    )
    result = await scorer.score(make_case(), "output text")
    assert result.passed


@pytest.mark.asyncio
async def test_llm_judge_custom_without_template_raises():
    provider = make_provider("{}")
    scorer = LLMJudge(provider, criteria="custom")
    with pytest.raises(ValueError, match="prompt_template"):
        await scorer.score(make_case(), "output")


@pytest.mark.asyncio
async def test_llm_judge_unknown_criterion_raises():
    provider = make_provider("{}")
    scorer = LLMJudge(provider, criteria="unknown_criterion")
    with pytest.raises(ValueError, match="Unknown criterion"):
        await scorer.score(make_case(), "output")


@pytest.mark.asyncio
async def test_llm_judge_model_override_passed_to_provider():
    provider = make_provider('{"score": 0.8, "passed": true, "reason": ""}')
    scorer = LLMJudge(provider, criteria="relevance", model="gpt-4o")
    await scorer.score(make_case(), "some output")
    call_kwargs = provider.complete.call_args[0][0]
    assert call_kwargs.model == "gpt-4o"


# ---------------------------------------------------------------------------
# LLMJudge — multi-criteria
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_judge_multi_criteria_avg():
    # Two calls: factuality=0.8, completeness=0.6 → avg=0.7 → passed
    responses = [
        '{"score": 0.8, "passed": true, "reason": "good"}',
        '{"score": 0.6, "passed": false, "reason": "missing points"}',
    ]
    provider = MagicMock()
    resp_objs = [MagicMock(content=r) for r in responses]
    provider.complete = AsyncMock(side_effect=resp_objs)

    scorer = LLMJudge(provider, criteria=["factuality", "completeness"], threshold=0.7, aggregate="avg")
    assert scorer.scorer_id == "llm-judge:factuality+completeness"
    result = await scorer.score(make_case(), "answer")
    assert result.score == pytest.approx(0.7)
    assert result.passed  # 0.7 >= 0.7


@pytest.mark.asyncio
async def test_llm_judge_multi_criteria_min():
    responses = [
        '{"score": 0.9, "passed": true, "reason": ""}',
        '{"score": 0.5, "passed": false, "reason": "bad"}',
    ]
    provider = MagicMock()
    resp_objs = [MagicMock(content=r) for r in responses]
    provider.complete = AsyncMock(side_effect=resp_objs)

    scorer = LLMJudge(provider, criteria=["factuality", "completeness"], aggregate="min", threshold=0.7)
    result = await scorer.score(make_case(), "answer")
    assert result.score == pytest.approx(0.5)
    assert not result.passed


@pytest.mark.asyncio
async def test_llm_judge_multi_criteria_all():
    # aggregate="all" → passed only if ALL criteria pass
    responses = [
        '{"score": 0.9, "passed": true, "reason": ""}',
        '{"score": 0.8, "passed": false, "reason": "missing"}',
    ]
    provider = MagicMock()
    resp_objs = [MagicMock(content=r) for r in responses]
    provider.complete = AsyncMock(side_effect=resp_objs)

    scorer = LLMJudge(provider, criteria=["factuality", "completeness"], aggregate="all")
    result = await scorer.score(make_case(), "answer")
    assert not result.passed  # one criterion failed


@pytest.mark.asyncio
async def test_llm_judge_custom_scorer_id():
    provider = make_provider('{"score": 1.0, "passed": true, "reason": ""}')
    scorer = LLMJudge(provider, scorer_id="my-judge")
    result = await scorer.score(make_case(), "output")
    assert result.scorer_id == "my-judge"


# ---------------------------------------------------------------------------
# SemanticSimilarity
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_semantic_similarity_scorer_id():
    provider = make_provider('{"score": 0.9, "passed": true, "reason": "same meaning"}')
    scorer = SemanticSimilarity(provider=provider)
    result = await scorer.score(make_case(expected="The capital is Paris"), "Paris is the capital")
    assert result.scorer_id == "semantic-similarity"
    assert result.passed


@pytest.mark.asyncio
async def test_semantic_similarity_threshold_override():
    provider = make_provider('{"score": 0.75, "passed": true, "reason": "close"}')
    scorer = SemanticSimilarity(provider=provider, threshold=0.8)
    result = await scorer.score(make_case(), "output")
    # JSON says passed=true but threshold check: score 0.75 < 0.8
    # JSON field "passed" wins here since it's explicitly set
    assert result.passed  # JSON-provided "passed" takes precedence


# ---------------------------------------------------------------------------
# Composite with LLMJudge
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_composite_with_llm_judge():
    provider = make_provider('{"score": 0.8, "passed": true, "reason": "good"}')
    judge = LLMJudge(provider, criteria="factuality")
    exact = ExactMatch()

    composite = Composite("combined", [judge, exact])
    # ExactMatch will fail (output != expected), LLMJudge will pass
    case = make_case(expected="exact answer")
    result = await composite.score(case, "different answer")
    # ExactMatch: score=0.0; LLMJudge: score=0.8 → avg=0.4; AND logic → not passed
    assert not result.passed
    assert result.score == pytest.approx(0.4)
