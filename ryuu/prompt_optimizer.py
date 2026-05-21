"""Phase 13 — PromptOptimizer: auto-tune prompts via eval feedback loop.

Pattern (inspired by DSPy, OpenAI Prompt Optimizer beta):
  1. Run eval suite against base prompt → baseline score
  2. Generate N variant prompts (rule-based or LLM-paraphrased)
  3. Evaluate each variant against eval suite
  4. Pick highest-scoring variant
  5. Use it as new base for next round
  6. Repeat for max_rounds, return best overall

Usage::

    from ryuu import Agent
    from ryuu.prompt_optimizer import PromptOptimizer, EvalCase, llm_variant_generator

    cases = [
        EvalCase(input="What is 2+2?", expected="4"),
        EvalCase(input="What is 10*5?", expected="50"),
    ]

    base = Agent(model="gpt-4o-mini", instructions="You are a math tutor")
    optimizer = PromptOptimizer(
        base_agent=base,
        eval_cases=cases,
        score_fn=lambda out, exp: 1.0 if exp in out else 0.0,
        variant_generator=llm_variant_generator(provider=base._agent.llm),
        max_rounds=3,
    )

    result = await optimizer.optimize()
    print(f"Best prompt: {result.best_prompt} (score {result.best_score:.2f})")
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from ryuu.factory import Agent
from ryuu.providers.llm import CompletionRequest, ILLMProvider, Message

__all__ = [
    "EvalCase",
    "PromptOptimizer",
    "OptimizationResult",
    "llm_variant_generator",
]


@dataclass(frozen=True)
class EvalCase:
    """Single eval test case: input + expected output."""

    input: str
    expected: str


@dataclass
class OptimizationResult:
    """Final result of PromptOptimizer.optimize()."""

    best_prompt: str
    best_score: float
    history: list[tuple[str, float]] = field(default_factory=list)
    rounds_completed: int = 0


ScoreFn = Callable[[str, str], float | Awaitable[float]]
VariantGenerator = Callable[[str], list[str] | Awaitable[list[str]]]


@dataclass
class PromptOptimizer:
    """Auto-tune prompts by evaluating variants against test cases.

    `score_fn(output, expected) -> float` — return 0.0 to 1.0 (higher = better).
    `variant_generator(current_prompt) -> list[str]` — produce N alternatives.
    """

    base_agent: Agent
    eval_cases: list[EvalCase]
    score_fn: ScoreFn
    variant_generator: VariantGenerator
    max_rounds: int = 3

    def __post_init__(self) -> None:
        if not self.eval_cases:
            raise ValueError("eval_cases must be non-empty")
        if self.max_rounds < 1:
            raise ValueError(f"max_rounds must be >= 1, got {self.max_rounds}")

    async def optimize(self) -> OptimizationResult:
        """Run optimization loop. Returns best prompt across all rounds."""
        history: list[tuple[str, float]] = []

        # Evaluate base
        base_prompt = self.base_agent.instructions
        base_score = await self._evaluate(base_prompt)
        history.append((base_prompt, base_score))

        best_prompt = base_prompt
        best_score = base_score
        current_prompt = base_prompt

        for round_idx in range(self.max_rounds):
            variants = await _maybe_await(self.variant_generator(current_prompt))

            for variant in variants:
                score = await self._evaluate(variant)
                history.append((variant, score))
                if score > best_score:
                    best_prompt = variant
                    best_score = score

            # Continue from best for next round (greedy)
            current_prompt = best_prompt

        return OptimizationResult(
            best_prompt=best_prompt,
            best_score=best_score,
            history=history,
            rounds_completed=self.max_rounds,
        )

    async def _evaluate(self, prompt: str) -> float:
        """Run all eval cases against `prompt`. Return mean score."""
        # Build a transient agent with the candidate prompt
        agent = self._clone_with_prompt(prompt)

        total = 0.0
        for case in self.eval_cases:
            result = await agent.run(case.input)
            output = result.output
            score_val = await _maybe_await(self.score_fn(output, case.expected))
            total += float(score_val)
        return total / len(self.eval_cases)

    def _clone_with_prompt(self, prompt: str) -> Agent:
        """Create a sibling Agent sharing the base's LLM but new instructions.

        Replicates internal LLM (so FakeLLMProvider queue continues), system_prompt
        on the internal agent so `_execute` picks up the new prompt.
        """
        # Shallow approach: mutate internal _FactoryLLMAgent.system_prompt directly.
        # Safe for optimization use-case since base_agent is sacrificed during tuning.
        self.base_agent._agent.system_prompt = prompt  # type: ignore[attr-defined]
        return self.base_agent


async def _maybe_await(value: Any) -> Any:
    """Await if awaitable, else return as-is."""
    if inspect.isawaitable(value):
        return await value
    return value


# ---------------------------------------------------------------------------
# Built-in variant generators
# ---------------------------------------------------------------------------


def llm_variant_generator(
    provider: ILLMProvider,
    n_variants: int = 3,
    model: str = "gpt-4o-mini",
) -> VariantGenerator:
    """Built-in variant generator using LLM paraphrasing.

    Returns an async callable suitable for `PromptOptimizer.variant_generator=`.
    Asks LLM to produce N paraphrased/improved versions of the current prompt.
    """

    async def _gen(current_prompt: str) -> list[str]:
        request = CompletionRequest(
            messages=[
                Message(role="system", content=(
                    f"You are a prompt engineer. Produce {n_variants} alternative "
                    f"system prompts that are paraphrased OR improved versions of the "
                    f"input. Return one variant per line, no numbering, no preamble."
                )),
                Message(role="user", content=current_prompt),
            ],
            model=model,
            temperature=0.7,
        )
        response = await provider.complete(request)
        # Parse one variant per non-empty line
        lines = [line.strip() for line in response.content.split("\n") if line.strip()]
        # Strip leading "Variant N:" / "1." / "-" prefixes if present
        cleaned: list[str] = []
        for line in lines:
            for prefix in ("Variant ", "variant ", "- ", "* "):
                if line.startswith(prefix):
                    line = line[len(prefix):].lstrip(":. ")
                    break
            # Also strip "1. ", "2. " style numbering
            if len(line) > 2 and line[0].isdigit() and line[1] in ".):":
                line = line[2:].lstrip()
            if line:
                cleaned.append(line)
        return cleaned[:n_variants]

    return _gen
