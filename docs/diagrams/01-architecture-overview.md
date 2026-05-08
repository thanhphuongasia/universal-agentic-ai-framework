# Architecture Overview

High-level tier diagram of the UAAF framework. Each tier has a single responsibility; tiers communicate through Protocols (interfaces), not concrete types.

```mermaid
graph TB
    subgraph User["User / Application"]
        REQ[Request / Task]
    end

    subgraph Intent["Intent Tier  uaaf/intent/"]
        IA[IIntentAnalyzer\nProtocol]
        SS[StrategySelector]
        IM[StructuredIntent\nComplexityLevel · ModelTier]
        LIA[LLMIntentAnalyzer\nconcrete]
        IA --> IM
        LIA -.implements.-> IA
        SS --> IM
    end

    subgraph Cognitive["Cognitive Tier  uaaf/cognitive/"]
        ICS[ICognitiveStrategy\nProtocol]
        DS[DirectStrategy]
        RS[ReActStrategy]
        EOS[EvaluatorOptimizer\nStrategy]
        PAR[ParallelStrategy]
        IV[IVerifier Protocol]
        SV[SchemaVerifier]
        LJ[LLMJudgeVerifier]
        GT[GroundTruthVerifier]
        VP[VerifierPipeline]
        DS & RS & EOS & PAR -.implements.-> ICS
        SV & LJ & GT & VP -.implements.-> IV
    end

    subgraph Execution["Execution Tier  uaaf/execution/"]
        BA[BaseAgent\nABC · template method]
        LA[LLMAgent\nextends BaseAgent]
        AP[AgentPool\nfan_out / fan_in]
        TR[ToolRegistry]
        IT[ITool Protocol]
        RL[react_loop\nThought→Action→Obs]
        BA --> LA
        LA --> RL
        RL --> TR
        TR --> IT
    end

    subgraph Providers["Providers Tier  uaaf/providers/"]
        ILLM[ILLMProvider\nProtocol]
        OAI[OpenAIProvider]
        ANT[AnthropicProvider]
        MR[ModelRouter\nCHEAP/STANDARD/POWERFUL]
        CB[CircuitBreaker]
        FB[FallbackProvider]
        OAI & ANT -.implements.-> ILLM
        MR --> ILLM
        CB --> ILLM
        FB --> ILLM
    end

    subgraph Knowledge["Knowledge Tier  uaaf/knowledge/"]
        IKB[IKnowledgeBackbone\nProtocol]
        MB[MemoryBackbone\nworking + episodic]
        GB[GraphBackbone\nnode + edge store]
        HB[HybridBackbone\nmemory + graph]
        CA[ContextAssembler\ntoken-budget trim]
        MB & GB & HB -.implements.-> IKB
        CA --> IKB
    end

    subgraph Observability["Observability  uaaf/observability/"]
        CT[CostTracker\nbudget per scope]
        TR2[Tracer\nOpenTelemetry]
        AL[AuditLogger\nJSONL hash chain]
        RLA[RateLimiter\ntoken bucket]
        PRC[pricing.yaml\nper-model USD rates]
        CT --> PRC
    end

    subgraph Runtime["Runtime  uaaf/runtime/"]
        EC[ExecutionContext]
        CS[ContextScope\nuser_id · session_id · domain]
        EC --> CS
    end

    subgraph Prompts["Prompts  uaaf/prompts/"]
        PR[PromptRegistry\nYAML versioned]
        PC[PromptConfig\nversioned templates]
        PR --> PC
    end

    REQ --> IA
    IM --> SS
    SS --> ICS
    ICS --> BA
    BA --> ILLM
    BA --> IKB
    BA -.injected.-> CT & TR2 & AL & RLA
    BA --> EC
```

---

## Tier Responsibilities

| Tier | Answers | Key Interface |
|---|---|---|
| Intent | What does the user want? How complex? | `IIntentAnalyzer` |
| Cognitive | Which reasoning pattern should run? | `ICognitiveStrategy` |
| Execution | How does one agent run + tool-call? | `BaseAgent` / `LLMAgent` |
| Providers | Which LLM handles this request? | `ILLMProvider` |
| Knowledge | What context does the agent need? | `IKnowledgeBackbone` |
| Observability | Cost, latency, audit, rate limit | injected into `BaseAgent` |
| Prompts | How is the LLM instructed? | `PromptRegistry` |
| Runtime | Who is calling? What session? | `ExecutionContext` |

---

## Design Rules

1. **Protocols over classes** — tiers depend on `Protocol`, never on concrete implementations.
2. **Cross-cutting injected** — `CostTracker`, `Tracer`, `AuditLogger`, `RateLimiter` are constructor-injected into `BaseAgent`; product code cannot bypass them.
3. **`_execute()` only** — subclasses implement domain logic only; `execute()` is sealed.
4. **Vertical slices** — each request flows top-to-bottom; no tier calls a tier above it.
