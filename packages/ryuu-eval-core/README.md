# ryuu-eval-core

Eval framework primitives — types, Protocols, runner, fixture loader, renderers.

**No built-in scorer implementations.** Bring your own (`class MyScorer: scorer_id = "..."; async def score(...): ...`) or install `ryuu-eval-scorers` for the default ones (ExactMatch, JsonSubset, LLMJudgeScorer).
