# RYUU — Phase 1 (Intent + Strategy) — Task Breakdown

> Phase 1 goal: `StructuredIntent` schema + `IIntentAnalyzer` + `StrategySelector` + 3 strategies (Direct, ReAct, EvaluatorOptimizer) + `LLMIntentAnalyzer`. Product teams có thể subclass `IIntentAnalyzer` và register strategy để route requests.

**Status**: In progress
**Last Updated**: 2026-05-07
**Predecessors**: Phase 0 complete (v0.1.0a1), spec `ryuu-framework-spec.md`

---

## Task graph

```
P1-T01 Models ──────────────────────────────────────┐
                                                     │
P1-T02 Protocols (IIntentAnalyzer, ICognitiveStrategy, IAgentPool, IVerifier)
         │                                           │
         ├──→ P1-T03 StrategySelector ───────────────┤
         │                                           │
         ├──→ P1-T04 DirectStrategy ─────────────────┤
         │                                           ├──→ P1-T08 Test utilities
         ├──→ P1-T05 ReActStrategy ──────────────────┤
         │                                           │
         ├──→ P1-T06 EvaluatorOptimizerStrategy ─────┤
         │                                           │
         └──→ P1-T07 LLMIntentAnalyzer ──────────────┘
                                                     │
                                               P1-T09 Tests + contracts
                                                     │
                                               P1-T10 CI gate
```

---

## P1-T01. Intent models (`ryuu/intent/models.py`)

**Acceptance**:
- `ComplexityLevel` enum: `LOW`, `MEDIUM`, `HIGH`
- `ModelTier` enum: `CHEAP`, `STANDARD`, `POWERFUL`
- `StrategyId` type alias `str` + constants: `DIRECT = "direct"`, `REACT = "react"`, `EVALUATOR_OPTIMIZER = "evaluator_optimizer"`
- `StructuredIntent` frozen dataclass:
  - `intent_type: str`
  - `action: str`
  - `entities: dict[str, Any]`
  - `complexity: ComplexityLevel`
  - `confidence: float` (0.0–1.0)
  - `ambiguous: bool = False`
  - `clarification_questions: list[str] = field(default_factory=list)`
  - `suggested_strategy: StrategyId = DIRECT`
  - `suggested_model_tier: ModelTier = ModelTier.STANDARD`
- `CognitiveResult` frozen dataclass:
  - `content: str`
  - `confidence: float`
  - `reasoning: str = ""`
  - `evidence: list[Any] = field(default_factory=list)`
  - `strategy_id: str = ""`
- `CostEstimate` frozen dataclass:
  - `input_tokens_est: int`
  - `output_tokens_est: int`
  - `usd_est: float`
  - `steps_est: int = 1`

**Files**: `ryuu/intent/__init__.py`, `ryuu/intent/models.py`

---

## P1-T02. Protocols (`ryuu/intent/analyzer.py`, `ryuu/cognitive/strategy.py`)

**Acceptance**:
- `IIntentAnalyzer` `@runtime_checkable` Protocol:
  - `async def analyze(self, message: str, scope_key: str, history: list[dict] | None) -> StructuredIntent`
- `IAgentPool` `@runtime_checkable` Protocol:
  - `async def dispatch(self, task: Task) -> AgentResult`
- `VerificationResult` frozen dataclass: `passed: bool`, `confidence: float`, `feedback: str = ""`
- `IVerifier` `@runtime_checkable` Protocol (stub, Phase 2 expands):
  - `verifier_id: str`
  - `async def verify(self, output: str, context: ExecutionContext) -> VerificationResult`
- `ICognitiveStrategy` `@runtime_checkable` Protocol:
  - `strategy_id: str`
  - `def applicable(self, intent: StructuredIntent, context: ExecutionContext) -> bool`
  - `def estimate_cost(self, intent: StructuredIntent, context: ExecutionContext) -> CostEstimate`
  - `async def execute(self, intent: StructuredIntent, context: ExecutionContext, agent_pool: IAgentPool, verifier: IVerifier) -> CognitiveResult`

**Files**: `ryuu/intent/analyzer.py`, `ryuu/cognitive/__init__.py`, `ryuu/cognitive/strategy.py`

---

## P1-T03. StrategySelector (`ryuu/intent/selector.py`)

**Acceptance**:
- `StrategySelector(strategies: list[ICognitiveStrategy])`: ordered list, first match wins
- `select(intent, context) -> ICognitiveStrategy`: returns first strategy where `applicable()` is True
- Raises `ValueError` if no strategy matches (should not happen when `DirectStrategy` is always last)

**Files**: `ryuu/intent/selector.py`

---

## P1-T04. DirectStrategy (`ryuu/cognitive/strategies/direct.py`)

**Acceptance**:
- `strategy_id = "direct"`
- `applicable`: always `True` (catch-all)
- `estimate_cost`: returns `CostEstimate(input_tokens_est=500, output_tokens_est=200, usd_est=0.0001, steps_est=1)`
- `execute`: `await agent_pool.dispatch(Task(...))`, return `CognitiveResult(content=result.output, confidence=1.0, strategy_id="direct")`

**Files**: `ryuu/cognitive/strategies/__init__.py`, `ryuu/cognitive/strategies/direct.py`

---

## P1-T05. ReActStrategy (`ryuu/cognitive/strategies/react.py`)

**Acceptance**:
- `strategy_id = "react"`
- `applicable`: `intent.complexity >= ComplexityLevel.MEDIUM`
- `execute`: loop `max_steps` (default 6):
  1. Build think prompt: `"Given: {intent}\nObservations: {obs}\nThink step by step. If done, respond with DONE:<answer>. Otherwise: ACTION:<action>"`
  2. Dispatch to `agent_pool`
  3. If response starts with `DONE:` → stop, return result
  4. Otherwise treat as observation, continue
- Returns `CognitiveResult` with `strategy_id="react"`, `reasoning` = accumulated observations

**Files**: `ryuu/cognitive/strategies/react.py`

---

## P1-T06. EvaluatorOptimizerStrategy (`ryuu/cognitive/strategies/evaluator_optimizer.py`)

**Acceptance**:
- `strategy_id = "evaluator_optimizer"`
- `applicable`: `intent.complexity == ComplexityLevel.HIGH`
- `execute`: loop `max_rounds` (default 3):
  1. Generate: `await agent_pool.dispatch(generate_task)`
  2. Evaluate: `await verifier.verify(output, context)`
  3. If `result.passed` → return `CognitiveResult(confidence=result.confidence, ...)`
  4. Else add `result.feedback` to next generate prompt, continue
- After `max_rounds` without pass: return best result so far

**Files**: `ryuu/cognitive/strategies/evaluator_optimizer.py`

---

## P1-T07. LLMIntentAnalyzer (`ryuu/intent/llm_analyzer.py`)

**Acceptance**:
- `LLMIntentAnalyzer(provider: ILLMProvider, model: str | None = None, system_prompt: str | None = None)`
- `analyze(message, scope_key, history)`:
  1. Build prompt with `INTENT_SYSTEM_PROMPT` (JSON schema description)
  2. `response = await provider.complete(CompletionRequest(...))`
  3. Parse JSON from response → `StructuredIntent`
  4. On parse error: return `StructuredIntent(intent_type="unknown", action="clarify", complexity=LOW, confidence=0.3, ambiguous=True, clarification_questions=["Could you clarify your request?"])`
- `INTENT_SYSTEM_PROMPT` constant: instructs LLM to output JSON matching StructuredIntent schema

**Files**: `ryuu/intent/llm_analyzer.py`

---

## P1-T08. Test utilities (`ryuu/_testing/fakes.py` update)

**Acceptance**:
- `FakeIntentAnalyzer(default_intent: StructuredIntent | None)`: returns preset intent, tracks `call_count`
- `FakeAgentPool(responses: list[AgentResult] | None)`: pops next response, tracks `dispatch_count`
- `FakeVerifier(pass_sequence: list[bool])`: iterates through pass sequence, `verifier_id = "fake"`

**Files**: `ryuu/_testing/fakes.py`

---

## P1-T09. Tests

**Unit tests**:
- `tests/unit/intent/test_models.py` — StructuredIntent defaults, CognitiveResult, CostEstimate
- `tests/unit/intent/test_selector.py` — StrategySelector selection logic
- `tests/unit/cognitive/test_direct.py` — DirectStrategy execute + applicable
- `tests/unit/cognitive/test_react.py` — ReActStrategy loop termination, DONE detection
- `tests/unit/cognitive/test_evaluator_optimizer.py` — pass on first round, retry on fail, max_rounds
- `tests/unit/intent/test_llm_analyzer.py` — JSON parse success, parse error fallback

**Contract tests**:
- `tests/contract/test_strategy_contract.py` — parametrized over all 3 strategies
- `tests/contract/test_intent_analyzer_contract.py` — parametrized over FakeLLMIntentAnalyzer

**Integration**:
- `tests/integration/test_phase1_smoke.py` — intent → selector → strategy → CognitiveResult end-to-end

---

## P1-T10. CI gate

- [x] `ruff check ryuu/ tests/` → 0 violations (2026-05-07)
- [x] `mypy ryuu/ --ignore-missing-imports` → 0 errors, 33 source files (2026-05-07)
- [x] `pytest --cov=ryuu` → 192 passed, 88.77% coverage (2026-05-07)
- [ ] User review + approve
- [ ] Tag v0.1.0b1

---

## Cross-task gates (Phase 1 complete when all pass)

- [x] All acceptance criteria above pass
- [x] CI gate green (ruff + mypy + pytest ≥85%)
- [x] `FakeIntentAnalyzer` + `FakeAgentPool` usable by downstream product tests
- [x] Strategy contract test covers all 3 strategies
- [x] CHANGELOG v0.1.0b1 entry
- [ ] User review + approve merge to `main`
- [ ] Tag v0.1.0b1
