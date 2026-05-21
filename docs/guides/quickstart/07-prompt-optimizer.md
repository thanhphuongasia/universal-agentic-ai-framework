# Prompt Optimizer — Auto-Tune via Eval Loop (Phase 13)

← [Quickstart Index](README.md) | [All guides](../)

> Tự động tune system prompt qua eval feedback. Greedy hill climb: evaluate base → generate variants → pick best → repeat. Inspired by DSPy + OpenAI Prompt Optimizer beta.

---

## 1. Khi Nào Dùng

- ✅ Có **eval suite** (`(input, expected)` pairs) và muốn accuracy cao hơn
- ✅ Specialized domain (finance/medical/legal) — prompt khó manual tune
- ✅ Multiple model + cùng task — pick best prompt per model
- ❌ Không có eval data — không có cách đo "tốt hơn"
- ❌ Free-form creative output — không scorable

## 2. Cơ Bản

```python
from ryuu import Agent, EvalCase, PromptOptimizer
from ryuu.prompt_optimizer import llm_variant_generator

# 1. Eval suite — what "good" looks like
cases = [
    EvalCase(input="What is 2+2?", expected="4"),
    EvalCase(input="What is 10*5?", expected="50"),
    EvalCase(input="What is sqrt(16)?", expected="4"),
]

# 2. Score function — return 0..1
def score(output: str, expected: str) -> float:
    return 1.0 if expected in output else 0.0

# 3. Base agent với initial prompt
base = Agent(model="gpt-4o-mini", instructions="You are a math tutor")

# 4. Run optimizer
optimizer = PromptOptimizer(
    base_agent=base,
    eval_cases=cases,
    score_fn=score,
    variant_generator=llm_variant_generator(provider=base._agent.llm, n_variants=3),
    max_rounds=3,
)
result = await optimizer.optimize()

print(f"Best prompt:  {result.best_prompt}")
print(f"Best score:   {result.best_score:.2f}")
print(f"Rounds:       {result.rounds_completed}")
print(f"Tried:        {len(result.history)} variants")
```

## 3. Algorithm — Greedy Hill Climb

```
1. Evaluate base prompt on all eval_cases → baseline score
2. For each round (1 to max_rounds):
   - Call variant_generator(current_best_prompt) → N variants
   - For each variant: evaluate on all cases → mean score
   - Pick highest scorer (or keep current_best if no improvement)
3. Return best across all rounds + full history
```

**Tính chất:**
- **Greedy**: pick best per round; không backtrack
- **Stable**: nếu không variant nào tốt hơn base, base wins
- **Complete history**: `result.history` chứa tất cả (prompt, score) đã thử

## 4. Score Function

Bất kỳ callable `(output, expected) -> float` (0..1, async OK):

```python
# Exact match
def exact(out, exp):
    return 1.0 if out.strip() == exp else 0.0

# Contains substring
def contains(out, exp):
    return 1.0 if exp.lower() in out.lower() else 0.0

# Partial credit / multi-criteria
async def weighted(out, exp):
    score = 0.0
    if exp.lower() in out.lower(): score += 0.5
    if len(out) < 100:              score += 0.3   # brevity
    if not "?" in out:              score += 0.2   # confident answer
    return score

# Plug VerifierPipeline (Phase 2)
async def llm_judge(out, exp):
    result = await judge_agent.run(f"Output: {out}\nExpected: {exp}\nScore 0-1:")
    return float(result.output.strip())
```

## 5. Variant Generator

Bất kỳ callable `(current_prompt: str) -> list[str] | Awaitable[list[str]]`:

```python
# Built-in: LLM paraphrase
from ryuu.prompt_optimizer import llm_variant_generator
gen = llm_variant_generator(provider=fake_llm, n_variants=3)

# Manual rule-based mutations
def gen(current: str) -> list[str]:
    return [
        f"{current}\n\nThink step by step.",      # add CoT
        f"{current}\n\nReturn ONLY the answer.",  # constrain output
        f"You are a careful expert. {current}",   # add persona
    ]

# Hybrid (LLM-suggested + manual)
async def hybrid(current: str) -> list[str]:
    llm_variants = await llm_variant_generator(...)(current)
    manual = [f"{current} (be concise)"]
    return llm_variants + manual
```

## 6. `OptimizationResult`

```python
@dataclass
class OptimizationResult:
    best_prompt: str               # winning prompt across all rounds
    best_score: float              # its eval suite mean
    history: list[tuple[str, float]]   # all (prompt, score) attempts
    rounds_completed: int
```

Visualize:
```python
for prompt, score in result.history:
    print(f"  [{score:.2f}] {prompt[:60]}")
```

## 7. Tips

| Tip | Lý do |
|---|---|
| Bắt đầu với 5-10 eval cases | Đủ representative, không quá expensive |
| `max_rounds=2-3` cho lần đầu | Đo improvement, scale up nếu cần |
| `n_variants=3-5` per round | Diverse mà không waste cost |
| Mix easy + hard cases | Tránh overfit tới 1 kind of input |
| Cache scores nếu eval_cases stable | Không re-run base mỗi lần |
| Cost cap với `budget_usd` ở base_agent | Tránh runaway tuning cost |

## 8. Imports

```python
from ryuu import EvalCase, PromptOptimizer, OptimizationResult
from ryuu.prompt_optimizer import llm_variant_generator
```

## 9. Roadmap

| Feature | Status |
|---|---|
| Greedy hill climb | ✅ Phase 13 |
| LLM variant generator | ✅ Phase 13 |
| Rule-based variants (CoT/persona/format mutations) | 🔲 future |
| Bayesian / evolutionary search | 🔲 future |
| Multi-objective (accuracy + brevity + cost) | 🔲 future |
| Caching layer (skip re-eval của same prompt) | 🔲 future |
| Resume từ checkpoint | 🔲 future |
