"""ryuu-eval-scorers — Built-in Scorer implementations.

All classes satisfy the ``Scorer`` Protocol from ryuu-eval-core:

    async def score(self, case: EvalCase, output: str) -> ScoreResult: ...

Scorers shipped:

  ExactMatch    — strict string equality
  Contains      — substring / all-substrings present
  Regex         — regex fullmatch / search
  Constraint    — arbitrary predicate
  Threshold     — numeric threshold via score_fn
  Composite     — combine multiple scorers (AND / OR semantics)
  LLMJudge      — LLM-as-a-Judge with built-in criteria templates
  SemanticSimilarity — LLM-based meaning comparison (no embeddings required)
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from ryuu_eval_core.models import EvalCase, ScoreResult


# ---------------------------------------------------------------------------
# Simple deterministic scorers
# ---------------------------------------------------------------------------


class ExactMatch:
    """Pass when output.strip() == str(case.expected).strip()."""

    scorer_id = "exact-match"

    async def score(self, case: EvalCase, output: str) -> ScoreResult:
        passed = str(case.expected).strip() == output.strip()
        return ScoreResult(scorer_id=self.scorer_id, score=1.0 if passed else 0.0, passed=passed)


class Contains:
    """Pass when all required substrings appear in output (case-insensitive by default).

    Usage::

        Contains(["Paris", "France"])          # all must appear
        Contains("Paris")                      # single string shorthand
        Contains(["paris"], case_sensitive=True)
    """

    def __init__(
        self,
        required: str | list[str],
        *,
        case_sensitive: bool = False,
        scorer_id: str = "contains",
    ) -> None:
        self.scorer_id = scorer_id
        self._needles = [required] if isinstance(required, str) else required
        self._cs = case_sensitive

    async def score(self, _case: EvalCase, output: str) -> ScoreResult:
        haystack = output if self._cs else output.lower()
        results = [(n if self._cs else n.lower()) in haystack for n in self._needles]
        hit = sum(results)
        score = hit / len(results) if results else 0.0
        passed = all(results)
        missing = [n for n, ok in zip(self._needles, results) if not ok]
        reason = "" if passed else f"missing: {missing}"
        return ScoreResult(scorer_id=self.scorer_id, score=score, passed=passed, reason=reason)


class Regex:
    """Pass when output matches a regex pattern.

    Usage::

        Regex(r"\\d{4}-\\d{2}-\\d{2}")        # fullmatch
        Regex(r"error", mode="search")          # anywhere in output
    """

    def __init__(
        self,
        pattern: str,
        *,
        mode: str = "search",
        flags: int = re.IGNORECASE,
        scorer_id: str = "regex",
    ) -> None:
        self.scorer_id = scorer_id
        self._re = re.compile(pattern, flags)
        self._mode = mode

    async def score(self, _case: EvalCase, output: str) -> ScoreResult:
        fn = self._re.fullmatch if self._mode == "fullmatch" else self._re.search
        passed = fn(output) is not None
        return ScoreResult(scorer_id=self.scorer_id, score=1.0 if passed else 0.0, passed=passed)


class Constraint:
    """Pass when predicate ``constraint_fn(output, case)`` returns True."""

    def __init__(self, scorer_id: str, constraint_fn: Callable[[str, EvalCase], bool]) -> None:
        self.scorer_id = scorer_id
        self._fn = constraint_fn

    async def score(self, case: EvalCase, output: str) -> ScoreResult:
        passed = bool(self._fn(output, case))
        return ScoreResult(scorer_id=self.scorer_id, score=1.0 if passed else 0.0, passed=passed)


class Threshold:
    """Pass when ``score_fn(output, case)`` returns >= ``min_score``."""

    def __init__(self, scorer_id: str, min_score: float, score_fn: Callable[[str, EvalCase], float]) -> None:
        self.scorer_id = scorer_id
        self._min = min_score
        self._fn = score_fn

    async def score(self, case: EvalCase, output: str) -> ScoreResult:
        s = float(self._fn(output, case))
        return ScoreResult(scorer_id=self.scorer_id, score=s, passed=s >= self._min)


class Composite:
    """Combine multiple scorers.

    ``require_all=True``  (default) → all must pass (AND)
    ``require_all=False`` → any must pass (OR)
    """

    def __init__(self, scorer_id: str, scorers: list[Any], require_all: bool = True) -> None:
        self.scorer_id = scorer_id
        self._scorers = scorers
        self._require_all = require_all

    async def score(self, case: EvalCase, output: str) -> ScoreResult:
        results = [await s.score(case, output) for s in self._scorers]
        avg = sum(r.score for r in results) / len(results) if results else 0.0
        passed = (all(r.passed for r in results) if self._require_all
                  else any(r.passed for r in results))
        reasons = [r.reason for r in results if r.reason]
        return ScoreResult(scorer_id=self.scorer_id, score=avg, passed=passed,
                           reason="; ".join(reasons))


# ---------------------------------------------------------------------------
# LLM-as-a-Judge
# ---------------------------------------------------------------------------

# Built-in criteria prompt templates.
# Each template instructs the judge to return JSON:
#   {"score": 0.0–1.0, "passed": bool, "reason": "..."}
#
# Use {{input}}, {{output}}, {{expected}} as placeholders.

CRITERIA_TEMPLATES: dict[str, str] = {
    "factuality": """\
You are an expert evaluator. Assess whether the AI output is factually accurate.

Input: {{input}}
AI Output: {{output}}
{% if expected %}Reference answer: {{expected}}{% endif %}

Respond with JSON only (no markdown fences):
{{"score": <0.0-1.0>, "passed": <true/false>, "reason": "<one sentence>"}}

Score guide:
  1.0 — fully accurate, no hallucinations
  0.7 — mostly accurate, minor imprecisions
  0.4 — partially correct but contains errors
  0.0 — largely incorrect or hallucinated
""",

    "completeness": """\
You are an expert evaluator. Assess whether the AI output is complete and covers all required points.

Input: {{input}}
AI Output: {{output}}
{% if expected %}Expected coverage: {{expected}}{% endif %}

Respond with JSON only (no markdown fences):
{{"score": <0.0-1.0>, "passed": <true/false>, "reason": "<one sentence>"}}

Score guide:
  1.0 — all required points covered
  0.7 — most points covered, minor gaps
  0.4 — significant omissions
  0.0 — largely incomplete
""",

    "relevance": """\
You are an expert evaluator. Assess whether the AI output is relevant and directly addresses the input.

Input: {{input}}
AI Output: {{output}}

Respond with JSON only (no markdown fences):
{{"score": <0.0-1.0>, "passed": <true/false>, "reason": "<one sentence>"}}

Score guide:
  1.0 — directly and fully addresses the question
  0.7 — mostly relevant with minor tangents
  0.4 — partially relevant, misses key point
  0.0 — irrelevant or off-topic
""",

    "hallucination": """\
You are an expert evaluator. Detect whether the AI output contains hallucinated or fabricated information.

Input: {{input}}
AI Output: {{output}}
{% if expected %}Ground truth: {{expected}}{% endif %}

Respond with JSON only (no markdown fences):
{{"score": <0.0-1.0>, "passed": <true/false>, "reason": "<one sentence>"}}

Score guide (higher = less hallucination):
  1.0 — no hallucinations detected
  0.7 — minor unsupported claims
  0.4 — notable fabrications present
  0.0 — severe hallucinations, mostly fabricated
""",

    "coherence": """\
You are an expert evaluator. Assess whether the AI output is coherent, well-structured, and easy to understand.

Input: {{input}}
AI Output: {{output}}

Respond with JSON only (no markdown fences):
{{"score": <0.0-1.0>, "passed": <true/false>, "reason": "<one sentence>"}}

Score guide:
  1.0 — clear, well-structured, easy to follow
  0.7 — mostly clear with minor confusion
  0.4 — hard to follow in parts
  0.0 — incoherent or self-contradictory
""",

    "semantic_match": """\
You are an expert evaluator. Assess whether the AI output conveys the same meaning as the expected answer, even if worded differently.

Input: {{input}}
AI Output: {{output}}
Expected: {{expected}}

Respond with JSON only (no markdown fences):
{{"score": <0.0-1.0>, "passed": <true/false>, "reason": "<one sentence>"}}

Score guide:
  1.0 — identical meaning
  0.7 — same core meaning, minor differences
  0.4 — partially matching meaning
  0.0 — different or opposite meaning
""",
}


def _render_template(template: str, input: Any, output: str, expected: Any) -> str:
    """Fill {{input}}, {{output}}, {{expected}} placeholders."""
    result = template
    result = result.replace("{{input}}", str(input))
    result = result.replace("{{output}}", output)
    result = result.replace("{{expected}}", str(expected) if expected is not None else "")
    # Remove Jinja-style conditional blocks (simple strip)
    result = re.sub(r"\{%.*?%\}", "", result, flags=re.DOTALL)
    return result.strip()


def _parse_judge_response(text: str, threshold: float) -> tuple[float, bool, str]:
    """Parse LLM judge response → (score, passed, reason).

    Tries JSON first, then regex extraction, then keyword fallback.
    """
    text = text.strip()

    # Strip markdown fences if present
    text_clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()

    try:
        data = json.loads(text_clean)
        score = float(data.get("score", 0.0))
        score = max(0.0, min(1.0, score))
        passed = bool(data.get("passed", score >= threshold))
        reason = str(data.get("reason", ""))
        return score, passed, reason
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    # Regex fallback: look for "score": 0.85 or score=0.85
    m = re.search(r'"?score"?\s*[:=]\s*([0-9]*\.?[0-9]+)', text, re.IGNORECASE)
    if m:
        score = max(0.0, min(1.0, float(m.group(1))))
        passed = score >= threshold
        return score, passed, text[:200]

    # Keyword fallback
    lower = text.lower()
    if "pass" in lower and "fail" not in lower:
        return 1.0, True, text[:200]
    if "fail" in lower:
        return 0.0, False, text[:200]

    return 0.0, False, f"unparseable response: {text[:100]}"


class LLMJudge:
    """LLM-as-a-Judge scorer.

    Uses an LLM provider to evaluate output quality across configurable criteria.
    Supports built-in criteria templates or a custom prompt template.

    Built-in criteria:
      - ``"factuality"``       — no hallucinations, factually correct
      - ``"completeness"``     — covers all required points
      - ``"relevance"``        — addresses the question
      - ``"hallucination"``    — absence of fabricated content
      - ``"coherence"``        — clear and well-structured
      - ``"semantic_match"``   — same meaning as expected (requires expected)

    Usage::

        from ryuu_eval_scorers import LLMJudge

        scorer = LLMJudge(
            criteria="factuality",
            provider=my_llm_provider,
            threshold=0.7,
        )

        # Custom prompt template:
        scorer = LLMJudge(
            criteria="custom",
            provider=my_llm_provider,
            prompt_template="Is this output safe?\\nOutput: {{output}}\\nReturn JSON: {{\\"score\\": ..., \\"passed\\": ..., \\"reason\\": ...}}",
        )

        # Multiple dimensions in one scorer:
        scorer = LLMJudge(
            criteria=["factuality", "completeness"],
            provider=my_llm_provider,
            aggregate="min",   # "min", "avg", "all"
        )
    """

    def __init__(
        self,
        provider: Any,
        *,
        criteria: str | list[str] = "factuality",
        threshold: float = 0.7,
        model: str = "",
        prompt_template: str | None = None,
        aggregate: str = "avg",
        scorer_id: str = "",
    ) -> None:
        """
        Args:
            provider:         ILLMProvider instance (e.g. OpenAIProvider).
            criteria:         Built-in criterion name(s) or "custom".
            threshold:        Score >= threshold → passed. Default 0.7.
            model:            Model name override. Empty = use provider default.
            prompt_template:  Custom prompt when criteria="custom". Use
                              {{input}}, {{output}}, {{expected}} placeholders.
            aggregate:        Multi-criteria aggregation: "avg", "min", "all".
                              "all" → passes only when all criteria pass.
            scorer_id:        Override scorer_id label. Default: criteria name(s).
        """
        self._provider = provider
        self._criteria = [criteria] if isinstance(criteria, str) else list(criteria)
        self._threshold = threshold
        self._model = model
        self._custom_template = prompt_template
        self._aggregate = aggregate

        if scorer_id:
            self.scorer_id = scorer_id
        elif len(self._criteria) == 1:
            self.scorer_id = f"llm-judge:{self._criteria[0]}"
        else:
            self.scorer_id = f"llm-judge:{'+'.join(self._criteria)}"

    def _build_prompt(self, criterion: str, case: EvalCase, output: str) -> str:
        if criterion == "custom":
            if self._custom_template is None:
                raise ValueError("criteria='custom' requires prompt_template=...")
            template = self._custom_template
        else:
            if criterion not in CRITERIA_TEMPLATES:
                raise ValueError(
                    f"Unknown criterion {criterion!r}. "
                    f"Available: {list(CRITERIA_TEMPLATES)}"
                )
            template = CRITERIA_TEMPLATES[criterion]
        return _render_template(template, case.input, output, case.expected)

    async def _judge_one(self, criterion: str, case: EvalCase, output: str) -> tuple[float, bool, str]:
        """Run a single LLM judgment call."""
        from ryuu_providers.llm import CompletionRequest, Message

        prompt = self._build_prompt(criterion, case, output)
        req = CompletionRequest(
            messages=[Message(role="user", content=prompt)],
            model=self._model,
            max_tokens=256,
            temperature=0.0,
        )
        resp = await self._provider.complete(req)
        return _parse_judge_response(resp.content, self._threshold)

    async def score(self, case: EvalCase, output: str) -> ScoreResult:
        if len(self._criteria) == 1:
            score, passed, reason = await self._judge_one(self._criteria[0], case, output)
            return ScoreResult(scorer_id=self.scorer_id, score=score, passed=passed, reason=reason)

        # Multi-criteria: call judge once per criterion
        results: list[tuple[float, bool, str]] = []
        for criterion in self._criteria:
            results.append(await self._judge_one(criterion, case, output))

        scores = [r[0] for r in results]
        passeds = [r[1] for r in results]
        reasons = [f"{c}: {r[2]}" for c, r in zip(self._criteria, results) if r[2]]

        if self._aggregate == "min":
            agg_score = min(scores)
        elif self._aggregate == "avg":
            agg_score = sum(scores) / len(scores)
        else:
            agg_score = sum(scores) / len(scores)

        if self._aggregate == "all":
            agg_passed = all(passeds)
        else:
            agg_passed = agg_score >= self._threshold

        return ScoreResult(
            scorer_id=self.scorer_id,
            score=agg_score,
            passed=agg_passed,
            reason="; ".join(reasons),
        )


class SemanticSimilarity(LLMJudge):
    """Convenience subclass: LLMJudge pre-configured for semantic_match.

    Requires ``case.expected`` to be set.

    Usage::

        SemanticSimilarity(provider=my_provider, threshold=0.8)
    """

    def __init__(self, provider: Any, *, threshold: float = 0.7, model: str = "") -> None:
        super().__init__(
            provider,
            criteria="semantic_match",
            threshold=threshold,
            model=model,
            scorer_id="semantic-similarity",
        )


# ---------------------------------------------------------------------------
# StructuredScorer
# ---------------------------------------------------------------------------


class StructuredScorer:
    """Compare structured JSON output against an expected nested dict.

    Implements the Scorer protocol — ``output`` is parsed as JSON, then
    compared against ``case.expected`` (must be a dict) using
    precision / recall / F1 and an optional hallucination check.

    Intended for evals where the production target emits a JSON string
    representing a nested mapping (e.g. entity → field → op, or any
    two-level dict).  Works for any project; normalization is injected.

    Args:
        threshold:        Minimum F1 to pass (default 0.85).
        key_normalizer:   Optional callable applied to every key before
                          comparison (e.g. snake_case → camelCase collapse).
                          Applied to both actual and expected keys.
        value_normalizer: Optional callable applied to leaf values before
                          comparison (e.g. sort op chars "RC" → "CR").
        valid_vocab:      Optional {outer_key: [inner_key, ...]} — used to
                          detect hallucination (inner keys absent from vocab).
                          Falls back to ``case.metadata["valid_fields"]`` if
                          not supplied at construction time.

    Usage::

        from eval_consumer.code_analysis.diagrams.crud_matrix.normalizer import (
            normalize_field, normalize_op,
        )
        scorer = StructuredScorer(
            threshold=0.85,
            key_normalizer=normalize_field,
            value_normalizer=normalize_op,
        )
    """

    def __init__(
        self,
        *,
        threshold: float = 0.85,
        key_normalizer: Callable[[str], str] | None = None,
        value_normalizer: Callable[[str], str] | None = None,
        valid_vocab: dict[str, list[str]] | None = None,
        scorer_id: str = "structured",
    ) -> None:
        self.scorer_id = scorer_id
        self._threshold = threshold
        self._norm_key: Callable[[str], str] = key_normalizer or (lambda x: x)
        self._norm_val: Callable[[str], str] = value_normalizer or (lambda x: x)
        self._valid_vocab = valid_vocab

    async def score(self, case: EvalCase, output: str) -> ScoreResult:
        try:
            actual_raw: dict = json.loads(output)
        except (json.JSONDecodeError, TypeError) as exc:
            return ScoreResult(
                scorer_id=self.scorer_id,
                score=0.0,
                passed=False,
                reason=f"output is not valid JSON: {exc}",
            )

        if not isinstance(case.expected, dict):
            return ScoreResult(
                scorer_id=self.scorer_id,
                score=0.0,
                passed=False,
                reason="case.expected must be a dict for StructuredScorer",
            )

        # valid_vocab: per-case override from metadata, fall back to constructor
        valid_vocab: dict[str, list[str]] | None = (
            case.metadata.get("valid_fields") or self._valid_vocab
        )

        metrics = _compute_structured(
            actual=actual_raw,
            expected=case.expected,
            valid_vocab=valid_vocab,
            norm_key=self._norm_key,
            norm_val=self._norm_val,
        )

        f1 = metrics["f1"]
        passed = f1 >= self._threshold
        reason = (
            f"precision={metrics['precision']:.3f} recall={metrics['recall']:.3f} "
            f"f1={f1:.3f} hallucination_rate={metrics['hallucination_rate']:.3f} "
            f"op_accuracy={metrics['op_accuracy']:.3f} "
            f"tp={metrics['tp']} fp={metrics['fp']} fn={metrics['fn']} "
            f"hallucinated={metrics['hallucinated']}"
        )
        return ScoreResult(scorer_id=self.scorer_id, score=f1, passed=passed, reason=reason)


def _compute_structured(
    actual: dict,
    expected: dict,
    valid_vocab: dict[str, list[str]] | None,
    norm_key: Callable[[str], str],
    norm_val: Callable[[str], str],
) -> dict:
    """Core structured comparison — returns a metrics dict.

    Both ``actual`` and ``expected`` are two-level dicts:
        {outer_key: {inner_key: value}}

    Outer keys (entities) are lowercased. Inner keys and values are
    normalised with the supplied callables.
    """
    # Normalise expected
    exp: dict[str, dict[str, str]] = {}
    for ok, inner in expected.items():
        exp[ok.lower()] = {norm_key(ik): norm_val(str(iv)) for ik, iv in inner.items()}

    # Normalise valid vocab
    vocab: dict[str, set[str]] = {}
    if valid_vocab:
        for ok, keys in valid_vocab.items():
            vocab[ok.lower()] = {norm_key(k) for k in keys}

    # Normalise actual
    act: dict[str, dict[str, str]] = {}
    for ok, inner in actual.items():
        act[ok.lower()] = {norm_key(ik): norm_val(str(iv)) for ik, iv in inner.items()}

    tp = fp = fn = hallucinated = name_matched = op_correct = 0

    for outer, a_inner in act.items():
        e_inner = exp.get(outer, {})
        v_keys = vocab.get(outer, set())

        for ik, av in a_inner.items():
            if v_keys and ik not in v_keys:
                hallucinated += 1
                fp += 1
                continue
            if ik in e_inner:
                name_matched += 1
                if av == e_inner[ik]:
                    tp += 1
                    op_correct += 1
                else:
                    fp += 1
            else:
                fp += 1

    for outer, e_inner in exp.items():
        a_inner = act.get(outer, {})
        for ik in e_inner:
            if ik not in a_inner:
                fn += 1

    total_act = sum(len(v) for v in act.values())
    total_exp = sum(len(v) for v in exp.values())
    precision = tp / total_act if total_act else 0.0
    recall = tp / total_exp if total_exp else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    hall_rate = hallucinated / total_act if total_act else 0.0
    op_acc = op_correct / name_matched if name_matched else 0.0

    return {
        "precision": precision, "recall": recall, "f1": f1,
        "hallucination_rate": hall_rate, "op_accuracy": op_acc,
        "tp": tp, "fp": fp, "fn": fn, "hallucinated": hallucinated,
        "name_matched": name_matched,
    }
