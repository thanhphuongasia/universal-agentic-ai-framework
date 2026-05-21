# Intent & Cognitive Tier — Class Diagram

`ryuu/intent/` + `ryuu/cognitive/` — understand the request, select a reasoning strategy, verify the output.

```mermaid
classDiagram
    class IIntentAnalyzer {
        <<Protocol>>
        +analyze(query, context) StructuredIntent
    }

    class LLMIntentAnalyzer {
        -llm: ILLMProvider
        +analyze(query, context) StructuredIntent
    }

    class StructuredIntent {
        <<frozen dataclass>>
        +query: str
        +domain: str
        +complexity: ComplexityLevel
        +preferred_tier: ModelTier
        +requires_tools: bool
        +metadata: dict
    }

    class ComplexityLevel {
        <<IntEnum>>
        LOW = 1
        MEDIUM = 2
        HIGH = 3
    }

    class ModelTier {
        <<StrEnum>>
        CHEAP = "cheap"
        STANDARD = "standard"
        POWERFUL = "powerful"
    }

    class CognitiveResult {
        <<frozen dataclass>>
        +output: str
        +strategy_id: str
        +verification: VerificationResult | None
        +cost: CostEstimate
        +metadata: dict
    }

    class StrategySelector {
        -_strategies: list[ICognitiveStrategy]
        +select(intent, context) ICognitiveStrategy
        +register(strategy)
    }

    class ICognitiveStrategy {
        <<Protocol>>
        +strategy_id: str
        +applicable(intent, context) bool
        +estimate_cost(intent, context) CostEstimate
        +execute(intent, context, pool, verifier) CognitiveResult
    }

    class DirectStrategy {
        +strategy_id = "direct"
        +applicable(intent, context) bool
        +execute(...) CognitiveResult
    }

    class ReActStrategy {
        +strategy_id = "react"
        +max_steps: int = 6
        +applicable(intent, context) bool
        +execute(...) CognitiveResult
    }

    class EvaluatorOptimizerStrategy {
        +strategy_id = "evaluator_optimizer"
        +max_iterations: int = 3
        +applicable(intent, context) bool
        +execute(...) CognitiveResult
    }

    class ParallelStrategy {
        +strategy_id = "parallel"
        +applicable(intent, context) bool
        +execute(...) CognitiveResult
    }

    class IVerifier {
        <<Protocol>>
        +verifier_id: str
        +verify(output, context) VerificationResult
    }

    class VerificationResult {
        <<frozen dataclass>>
        +passed: bool
        +score: float
        +feedback: str
        +metadata: dict
    }

    class SchemaVerifier {
        +required_keys: list[str]
        +required_substrings: list[str]
        +verify(output, context) VerificationResult
    }

    class LLMJudgeVerifier {
        -llm: ILLMProvider
        +criteria: str
        +verify(output, context) VerificationResult
    }

    class GroundTruthVerifier {
        +reference: str
        +mode: str  exact|substring|word_overlap
        +verify(output, context) VerificationResult
    }

    class VerifierPipeline {
        +verifiers: list[IVerifier]
        +mode: str  ALL_PASS|ANY_PASS|THRESHOLD
        +threshold: float
        +verify(output, context) VerificationResult
    }

    LLMIntentAnalyzer ..|> IIntentAnalyzer : implements
    IIntentAnalyzer --> StructuredIntent : returns
    StructuredIntent --> ComplexityLevel : has
    StructuredIntent --> ModelTier : has
    StrategySelector --> ICognitiveStrategy : selects
    StrategySelector --> StructuredIntent : reads
    ICognitiveStrategy --> CognitiveResult : returns
    DirectStrategy ..|> ICognitiveStrategy : implements
    ReActStrategy ..|> ICognitiveStrategy : implements
    EvaluatorOptimizerStrategy ..|> ICognitiveStrategy : implements
    ParallelStrategy ..|> ICognitiveStrategy : implements
    ICognitiveStrategy --> IVerifier : calls
    IVerifier --> VerificationResult : returns
    SchemaVerifier ..|> IVerifier : implements
    LLMJudgeVerifier ..|> IVerifier : implements
    GroundTruthVerifier ..|> IVerifier : implements
    VerifierPipeline ..|> IVerifier : implements
    VerifierPipeline --> IVerifier : composes
    CognitiveResult --> VerificationResult : embeds
```

---

## StrategySelector — Selection Logic

```
ComplexityLevel.LOW    → DirectStrategy      (single LLM call, no tools)
ComplexityLevel.MEDIUM → ReActStrategy       (Thought→Action→Obs loop)
ComplexityLevel.HIGH   → EvaluatorOptimizer  (generate → evaluate → refine)
requires_parallel=True → ParallelStrategy    (fan_out across AgentPool)
```

Strategies are checked via `applicable()` in priority order. First match wins.

---

## VerifierPipeline — Aggregation Modes

| Mode | Passes when |
|---|---|
| `ALL_PASS` | every verifier passes |
| `ANY_PASS` | at least one verifier passes |
| `THRESHOLD` | fraction of passing verifiers ≥ threshold |

```python
pipeline = VerifierPipeline(
    verifiers=[schema_v, ground_truth_v, llm_judge_v],
    mode="THRESHOLD",
    threshold=0.67,   # 2 of 3 must pass
)
```
