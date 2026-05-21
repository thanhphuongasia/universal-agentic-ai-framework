# Phase 14.1-14.6 — Claude-like Thinking Patterns Implementation Plan

> **Date**: 2026-05-21 (rev 2 — 2-layer architecture)
> **Triggered by**: Code analysis migration feedback — 5 thinking patterns per intent layer
> **Goal**: Promote universal patterns to framework, đúng tier placement
> **Effort estimate**: ~17h total (rev 1 was 14h, +3h for proper 2-layer)
> **Target version**: `0.3.0a12`
> **Architecture decision**: 2-layer (cognitive mechanism + Factory ergonomic)

---

## 1. Goal

Promote 4 universal "Claude-like Thinking Engine" patterns từ consumer self-impl → framework built-in, **đúng tier placement**:

| Pattern | Tier | Module |
|---|---|---|
| **#1+#2 Thinking Channel** | Cognitive | `ryuu-cognitive/strategies/thinking_strategy.py` |
| **#3+#4 Adaptive Compute** | Cognitive | `ryuu-cognitive/strategies/adaptive_strategy.py` |
| **#6+#7 Best-of-N** | Cognitive | `ryuu-cognitive/strategies/best_of_n_strategy.py` |
| **#9 Hierarchical Router** | Facade (routing) | `ryuu/facades.py` |

Factory expose **Option A**: kwargs convenience (90% use case) + `strategy=` explicit (advanced).

**LOC saving:** ~200 lines/pattern × 4 patterns = **800 lines deleted per app**.

---

## 2. Architecture — 2-Layer

```
┌─────────────────────────────────────────────────────────┐
│ LAYER B — Ergonomic (consumer-facing)                   │
├─────────────────────────────────────────────────────────┤
│ ryuu/factory.py:                                        │
│   Agent(thinking_mode=True)                             │
│   Agent(n_samples=3, vote="majority")                   │
│   Agent(adaptive_compute=True, tier_models={...})       │
│   Agent(strategy=BestOfNStrategy(n=5))   # advanced     │
│                                                         │
│ ryuu/facades.py:                                        │
│   HierarchicalRouter(category_classifier, routes_by_..)│
└─────────────────────────────────────────────────────────┘
                          │ delegates to
                          ▼
┌─────────────────────────────────────────────────────────┐
│ LAYER A — Mechanism (pure cognitive strategies)         │
├─────────────────────────────────────────────────────────┤
│ ryuu-cognitive/strategies/:                             │
│   ThinkingStrategy   — wraps base strategy + tag parse  │
│   BestOfNStrategy    — sample N + vote                  │
│   AdaptiveStrategy   — difficulty → tier dispatch       │
│   DirectStrategy     — existing                         │
│   ReActStrategy       — existing                         │
│   EvaluatorOptimizer — existing                         │
└─────────────────────────────────────────────────────────┘
```

**Lợi ích 2-layer:**
- Class-based `BaseAgent` dùng strategies trực tiếp (không bị lock Factory)
- Factory ergonomic kwargs mapping → strategy classes
- Test strategy isolated (không cần Factory)
- Sửa logic strategy → app dùng cả 2 cách đều update

---

## 3. Scope (IN / OUT)

### IN SCOPE

| Feature | Phase | Location |
|---|---|---|
| `ThinkingStrategy` cognitive strategy | 14.1 | `ryuu-cognitive/strategies/thinking_strategy.py` |
| `Agent(thinking_mode=True)` Factory wire | 14.1 | `ryuu/factory.py` |
| `AgentResult.thinking: str` field | 14.1 | `ryuu_core/models.py` |
| `BestOfNStrategy` (vote: majority/llm_judge/score_fn) | 14.2 | `ryuu-cognitive/strategies/best_of_n_strategy.py` |
| `Agent(n_samples=N, vote=..., confidence_threshold=...)` wire | 14.2 | `ryuu/factory.py` |
| `AdaptiveStrategy` (difficulty classifier + tier dispatch) | 14.3 | `ryuu-cognitive/strategies/adaptive_strategy.py` |
| `Agent(adaptive_compute=True, tier_models=..., tier_max_iterations=...)` wire | 14.3 | `ryuu/factory.py` |
| `strategy=<StrategyInstance>` explicit kwarg (Option A escape hatch) | 14.1-14.3 | `ryuu/factory.py` |
| `HierarchicalRouter` facade | 14.4 | `ryuu/facades.py` |
| Update migration guide §16 + architecture §7 | 14.5 | docs |
| Update `intent_patterns_demo.py` before/after | 14.6 | examples |

### OUT OF SCOPE

| Feature | Defer to |
|---|---|
| OODA structured strategy (#12) | Phase 14.x v2 |
| Adversarial verifier preset (#29) | Phase 14.x v2 |
| Architect-Editor explicit facade (#30) | Existing `Orchestrator` covers |
| Linter-in-the-Loop preset | Existing `hooks={"pre_tool": [linter]}` covers |
| Streaming `thinking` events qua `.stream()` | Phase 14.x v2 |
| Multi-step thinking (`<thinking>` per ReAct iteration) | Phase 14.x v2 |

---

## 4. File Structure

```
packages/ryuu-cognitive/src/ryuu_cognitive/strategies/
├── direct.py                         # existing
├── react.py                          # existing
├── evaluator_optimizer.py             # existing
├── parallel.py                        # existing
├── thinking_strategy.py               # NEW (Phase 14.1)
├── best_of_n_strategy.py               # NEW (Phase 14.2)
└── adaptive_strategy.py                # NEW (Phase 14.3)

packages/ryuu-cognitive/src/ryuu_cognitive/__init__.py   # MODIFY: re-export 3 new strategies

ryuu/
├── factory.py                          # MODIFY: kwargs + strategy= mapping
├── facades.py                          # MODIFY: add HierarchicalRouter
├── _thinking_parser.py                  # NEW (Phase 14.1): parse <thinking>/<answer>
├── _difficulty_classifier.py             # NEW (Phase 14.3): cheap default classifier
└── __init__.py                          # MODIFY: re-export HierarchicalRouter

packages/ryuu-core/src/ryuu_core/
└── models.py                            # MODIFY (Phase 14.1): AgentResult.thinking field

tests/unit/cognitive_pkg/                # NEW dir
├── test_thinking_strategy.py            # NEW (~6 tests Phase 14.1)
├── test_best_of_n_strategy.py            # NEW (~6 tests Phase 14.2)
└── test_adaptive_strategy.py             # NEW (~5 tests Phase 14.3)

tests/unit/ryuu/
├── test_factory_thinking.py             # NEW (~3 tests — Factory wire)
├── test_factory_best_of_n.py             # NEW (~3 tests — Factory wire)
├── test_factory_adaptive.py              # NEW (~3 tests — Factory wire)
└── test_hierarchical_router.py           # NEW (~5 tests Phase 14.4)

examples/code_analysis/
├── intent_patterns_demo.py              # UPDATE (Phase 14.6): before/after side-by-side
└── docs/2026-05-21_migration-to-ryuu.md  # UPDATE §16 (Phase 14.5)

docs/architecture/
└── uaaf-v2-architecture.md              # UPDATE §7 Cognitive Tier (Phase 14.5)
```

---

## 5. API Spec — Detailed

### 5.1 ThinkingStrategy + Factory wire (Phase 14.1)

#### Layer A — `ryuu-cognitive/strategies/thinking_strategy.py`

```python
from dataclasses import dataclass, field
from ryuu_cognitive.strategy import ICognitiveStrategy
from ryuu.intent.models import CognitiveResult, StructuredIntent

@dataclass
class ThinkingStrategy:
    """Wraps any base strategy with <thinking>/<answer> structured output.

    Parses LLM output → CognitiveResult.content (answer) + .thinking (reasoning).
    """
    strategy_id: str = "thinking"
    base_strategy: ICognitiveStrategy | None = None   # default: ReActStrategy

    def applicable(self, intent, context) -> bool:
        return True   # universal — always applicable

    async def execute(self, intent, context, agent_pool, verifier) -> CognitiveResult:
        # Augment intent.entities["system_prompt_suffix"] với template
        # Run base_strategy
        # Parse output → strip tags, populate result.thinking
        ...
```

**Internal:** Inject template
```
Produce response in two parts:
<thinking>...your reasoning, decompose problem, consider alternatives...</thinking>
<answer>...concise final answer...</answer>
Always emit BOTH tags.
```

Parse output via `ryuu/_thinking_parser.py`:
```python
def parse_thinking_answer(raw: str) -> tuple[str, str]:
    """Returns (answer, thinking). Fallback: (raw, '')."""
    thinking = re.search(r"<thinking>(.*?)</thinking>", raw, re.DOTALL)
    answer = re.search(r"<answer>(.*?)</answer>", raw, re.DOTALL)
    return (
        answer.group(1).strip() if answer else raw.strip(),
        thinking.group(1).strip() if thinking else "",
    )
```

#### Layer B — `ryuu/factory.py` wire

```python
@dataclass
class Agent:
    # ... existing fields
    thinking_mode: bool = False                   # NEW
    strategy: Any = None                           # NEW — explicit strategy override

    def __post_init__(self):
        # ... existing
        # Resolve strategy
        if self.strategy is not None:
            self._strategy = self.strategy
        elif self.thinking_mode:
            from ryuu_cognitive.strategies import ThinkingStrategy
            self._strategy = ThinkingStrategy()
        # ... other strategy detection
```

#### Layer C — `ryuu_core/models.py`

```python
@dataclass
class AgentResult:
    # ... existing fields
    thinking: str = ""   # NEW — populated when ThinkingStrategy used
```

### 5.2 BestOfNStrategy + Factory wire (Phase 14.2)

#### Layer A — `ryuu-cognitive/strategies/best_of_n_strategy.py`

```python
from typing import Literal, Callable

@dataclass
class BestOfNStrategy:
    strategy_id: str = "best_of_n"
    n: int = 3
    vote: Literal["majority", "llm_judge", "score_fn"] = "majority"
    confidence_threshold: float | None = None   # skip best-of-N if primary > threshold
    verifier: Any | None = None                   # for vote="llm_judge"
    score_fn: Callable[[str], float] | None = None   # for vote="score_fn"

    def applicable(self, intent, context) -> bool: ...
    async def execute(self, intent, context, agent_pool, verifier) -> CognitiveResult:
        # 1. If confidence_threshold: primary call first, parse confidence, skip if above
        # 2. Else: fan_out N tasks
        # 3. Aggregate via vote mode
        ...
```

#### Layer B — `ryuu/factory.py` wire

```python
@dataclass
class Agent:
    # ... existing
    n_samples: int = 1                            # NEW — > 1 triggers BestOfNStrategy
    vote: Literal["majority", "llm_judge", "score_fn"] = "majority"   # NEW
    confidence_threshold: float | None = None      # NEW

    def __post_init__(self):
        # If n_samples > 1: self._strategy = BestOfNStrategy(...)
        ...
```

### 5.3 AdaptiveStrategy + Factory wire (Phase 14.3)

#### Layer A — `ryuu-cognitive/strategies/adaptive_strategy.py`

```python
@dataclass
class AdaptiveStrategy:
    strategy_id: str = "adaptive"
    difficulty_classifier: Any | None = None   # default: cheap classifier
    tier_models: dict[str, str] = field(default_factory=lambda: {
        "trivial": "gpt-4o-mini",
        "medium":  "gpt-4o-mini",
        "hard":    "gpt-4o",
    })
    tier_max_iterations: dict[str, int] = field(default_factory=lambda: {
        "trivial": 2, "medium": 4, "hard": 8,
    })
    tier_max_tokens: dict[str, int] = field(default_factory=lambda: {
        "trivial": 300, "medium": 800, "hard": 2000,
    })

    def applicable(self, intent, context) -> bool: ...
    async def execute(self, intent, context, agent_pool, verifier) -> CognitiveResult:
        # 1. Classify difficulty via difficulty_classifier.run(intent.action)
        # 2. Map to tier model + iterations + max_tokens
        # 3. Dispatch via agent_pool with overrides
        ...
```

#### Layer B — `ryuu/factory.py` wire

```python
@dataclass
class Agent:
    # ... existing
    adaptive_compute: bool = False                # NEW
    tier_models: dict[str, str] | None = None     # NEW (override defaults)
    tier_max_iterations: dict[str, int] | None = None
    tier_max_tokens: dict[str, int] | None = None

    def __post_init__(self):
        # If adaptive_compute: self._strategy = AdaptiveStrategy(...)
        ...
```

### 5.4 HierarchicalRouter Facade (Phase 14.4)

#### `ryuu/facades.py`

```python
@dataclass
class HierarchicalRouter:
    """2-stage routing: category → specific intent within category.

    NOT a cognitive strategy — this is routing concern (đi đâu, không phải nghĩ như nào).
    """
    category_classifier: Agent
    routes_by_category: dict[str, dict[str, Any]]   # {category: {intent: agent}}
    fallback_route: str | None = None
    specific_analyzer: Callable[[str, list[str]], str] | None = None   # custom stage 2

    async def run(self, input_value: Any) -> Any:
        # Stage 1: category = await category_classifier.run(input)
        category = (await self.category_classifier.run(str(input_value))).output.strip()
        options_dict = self.routes_by_category.get(category)
        if options_dict is None:
            if self.fallback_route:
                return await _run_step(self.routes_by_category[self.fallback_route], input_value)
            raise KeyError(f"category {category!r} not in routes_by_category")

        # Stage 2: pick specific intent
        if self.specific_analyzer:
            intent = self.specific_analyzer(str(input_value), list(options_dict))
        else:
            # Default: build inline classifier with options
            intent = await self._llm_pick(input_value, list(options_dict))

        return await _run_step(options_dict[intent], input_value)
```

### 5.5 Option A — kwargs + explicit `strategy=`

User chọn 1 trong 2:

```python
# Cách 1: kwargs (90% use case)
agent = Agent(model="gpt-4o", thinking_mode=True)
agent = Agent(model="gpt-4o", n_samples=3, vote="majority")
agent = Agent(model="gpt-4o", adaptive_compute=True, tier_models={...})

# Cách 2: strategy= explicit (advanced — custom config)
from ryuu_cognitive.strategies import BestOfNStrategy, ThinkingStrategy
agent = Agent(model="gpt-4o", strategy=BestOfNStrategy(n=5, vote="llm_judge", verifier=judge))
agent = Agent(model="gpt-4o", strategy=ThinkingStrategy(base_strategy=ReActStrategy()))
```

**Validation:** `kwargs` và `strategy=` mutually exclusive. Setting cả 2 → ValueError.

---

## 6. Test Strategy (TDD)

### 6.1 Per-layer tests

**Layer A — strategies tested độc lập (no Factory):**

```python
# tests/unit/cognitive_pkg/test_thinking_strategy.py
async def test_thinking_strategy_parses_tags() -> None:
    strategy = ThinkingStrategy()
    intent = make_intent("test")
    result = await strategy.execute(intent, ctx, agent_pool, verifier)
    assert "<thinking>" not in result.content       # stripped
    assert result.thinking != ""                    # populated
```

**Layer B — Factory wiring tested:**

```python
# tests/unit/ryuu/test_factory_thinking.py
async def test_factory_thinking_mode_uses_thinking_strategy() -> None:
    agent = Agent(model="gpt-4o-mini", thinking_mode=True)
    assert isinstance(agent._strategy, ThinkingStrategy)

async def test_factory_strategy_explicit_overrides_kwargs() -> None:
    custom = BestOfNStrategy(n=10)
    agent = Agent(model="gpt-4o-mini", strategy=custom)
    assert agent._strategy is custom

def test_factory_kwargs_and_strategy_mutually_exclusive() -> None:
    with pytest.raises(ValueError, match="strategy"):
        Agent(model="gpt-4o-mini", thinking_mode=True, strategy=ThinkingStrategy())
```

### 6.2 Total test count

| Test file | Layer | Cases |
|---|---|---|
| `test_thinking_strategy.py` | A | 6 |
| `test_best_of_n_strategy.py` | A | 6 |
| `test_adaptive_strategy.py` | A | 5 |
| `test_factory_thinking.py` | B | 3 |
| `test_factory_best_of_n.py` | B | 3 |
| `test_factory_adaptive.py` | B | 3 |
| `test_hierarchical_router.py` | B | 5 |
| **Total** | | **31** |

### 6.3 Regression target

Existing 930 unit + 7 perf + 3 integration → **961 unit + 7 perf + 3 integration** after Phase 14.x.

---

## 7. Implementation Order

```
T1 (3h): Phase 14.1 — ThinkingStrategy
  - 1.1: ryuu_cognitive/strategies/thinking_strategy.py (1.5h)
  - 1.2: ryuu/_thinking_parser.py (15m)
  - 1.3: ryuu_core/models.py — add AgentResult.thinking (15m)
  - 1.4: ryuu/factory.py — wire thinking_mode + strategy= (45m)
  - 1.5: 6 cognitive + 3 factory tests (15m)

T2 (4h): Phase 14.2 — BestOfNStrategy
  - 2.1: ryuu_cognitive/strategies/best_of_n_strategy.py (2h)
  - 2.2: ryuu/factory.py — wire n_samples + vote + confidence_threshold (1h)
  - 2.3: 6 cognitive + 3 factory tests (1h)

T3 (4h): Phase 14.3 — AdaptiveStrategy
  - 3.1: ryuu/_difficulty_classifier.py (30m)
  - 3.2: ryuu_cognitive/strategies/adaptive_strategy.py (2h)
  - 3.3: ryuu/factory.py — wire adaptive_compute + tier_* (1h)
  - 3.4: 5 cognitive + 3 factory tests (30m)

T4 (3h): Phase 14.4 — HierarchicalRouter
  - 4.1: ryuu/facades.py — add HierarchicalRouter class (2h)
  - 4.2: ryuu/__init__.py — re-export (15m)
  - 4.3: 5 facade tests (45m)

T5 (1h): Phase 14.5 — Docs
  - 5.1: Update docs/architecture/uaaf-v2-architecture.md §7
  - 5.2: Update examples/code_analysis/docs/2026-05-21_migration-to-ryuu.md §16

T6 (2h): Phase 14.6 — Demo + release
  - 6.1: Update examples/code_analysis/intent_patterns_demo.py (before/after)
  - 6.2: Update CHANGELOG.md
  - 6.3: Bump pyproject.toml + ryuu/__init__.py 0.3.0a11 → 0.3.0a12
  - 6.4: Update tests/integration/test_phase7_smoke.py version assertion
  - 6.5: Full regression check
```

**Total: 17h.**

---

## 8. Definition of Done

- [ ] Layer A — 3 strategies trong `ryuu-cognitive/strategies/`
  - [ ] ThinkingStrategy + `_thinking_parser.py`
  - [ ] BestOfNStrategy (3 vote modes)
  - [ ] AdaptiveStrategy + `_difficulty_classifier.py`
- [ ] Layer B — Factory + facades
  - [ ] `Agent(thinking_mode=True)` wires to ThinkingStrategy
  - [ ] `Agent(n_samples=N, vote=...)` wires to BestOfNStrategy
  - [ ] `Agent(adaptive_compute=True, tier_models=...)` wires to AdaptiveStrategy
  - [ ] `Agent(strategy=<instance>)` explicit override
  - [ ] kwargs/strategy mutually exclusive validation
  - [ ] HierarchicalRouter facade
- [ ] AgentResult.thinking field added (backward-compat)
- [ ] 31 new tests GREEN
- [ ] No regression on existing 930 tests
- [ ] Re-exports updated: `ryuu_cognitive`, `ryuu/__init__.py`
- [ ] CHANGELOG.md Phase 14.1-14.6 entry
- [ ] Migration guide §16 updated
- [ ] Architecture §7 updated
- [ ] Demo before/after shows clear LOC reduction
- [ ] Version 0.3.0a11 → 0.3.0a12

---

## 9. Risk & Mitigation

| Risk | Mitigation |
|---|---|
| ThinkingStrategy parse fail on malformed output | Fallback: `thinking = ""`, treat raw as answer |
| BestOfN cost explosion (N×) | `confidence_threshold` gate; documented trade-off |
| AdaptiveStrategy classifier latency overhead | Cache result per (query, session); opt-out via flag |
| HierarchicalRouter 2 LLM calls vs 1 flat | Document (+1 call ≈ $0.0001 gpt-4o-mini, accuracy +10-20%) |
| kwargs vs strategy= conflict | Mutual exclusion validation with clear error |
| Existing tests break from new fields | All new fields default None/False → backward compat |
| Strategy class import in Factory creates circular dep | Lazy import in `__post_init__` |

---

## 10. Post-Ship Validation

```bash
# 1. Layer A tests
pytest tests/unit/cognitive_pkg/test_thinking_strategy.py \
       tests/unit/cognitive_pkg/test_best_of_n_strategy.py \
       tests/unit/cognitive_pkg/test_adaptive_strategy.py -v

# 2. Layer B tests
pytest tests/unit/ryuu/test_factory_thinking.py \
       tests/unit/ryuu/test_factory_best_of_n.py \
       tests/unit/ryuu/test_factory_adaptive.py \
       tests/unit/ryuu/test_hierarchical_router.py -v

# 3. Full regression
pytest --tb=no -q --ignore=tests/perf

# 4. Run updated demo
python -m examples.code_analysis.intent_patterns_demo

# 5. Verify version
python -c "import ryuu; print(ryuu.__version__)"  # → 0.3.0a12

# 6. Verify strategies importable
python -c "
from ryuu_cognitive.strategies import (
    ThinkingStrategy, BestOfNStrategy, AdaptiveStrategy,
)
print('Layer A: 3 new strategies importable')
"

# 7. Verify Factory ergonomic kwargs
python -c "
from ryuu import Agent, HierarchicalRouter
import os; os.environ['OPENAI_API_KEY'] = 'sk-test'
a = Agent(model='gpt-4o-mini', thinking_mode=True)
b = Agent(model='gpt-4o-mini', n_samples=3, vote='majority')
c = Agent(model='gpt-4o-mini', adaptive_compute=True)
print('Layer B: 3 Factory kwargs work + HierarchicalRouter exported')
"
```
