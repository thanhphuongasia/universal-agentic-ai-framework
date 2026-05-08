# Request Flow — Sequence Diagrams

End-to-end flow for the two most common patterns.

---

## Pattern A: LLMAgent with Tool Calling (most common)

```mermaid
sequenceDiagram
    participant App
    participant Agent as LLMAgent._execute()
    participant RL as react_loop()
    participant LLM as ILLMProvider
    participant TR as ToolRegistry
    participant KB as IKnowledgeBackbone

    App->>Agent: execute(task, context)
    Note over Agent: BaseAgent.execute() runs first:<br/>rate_limit → budget_check → audit_start

    Agent->>KB: assemble_context(query, scope_key)
    KB-->>Agent: AssembledContext (trimmed to budget)

    Agent->>RL: react_loop(request, max_rounds=3)

    loop Round 1..N
        RL->>LLM: complete(CompletionRequest)
        LLM-->>RL: Response(content, tool_calls, usage)

        alt no tool_calls
            RL-->>Agent: (final_text, TokenUsage)
        else tool_calls present
            RL->>TR: run_all(tool_calls, domain)
            TR-->>RL: list[{tool_call_id, content}]
            Note over RL: append assistant + tool messages
        else max_rounds exceeded
            RL->>LLM: complete(synthesis_request, tools=None)
            LLM-->>RL: Response
            RL-->>Agent: (synthesized_text, TokenUsage)
        end
    end

    Agent->>KB: write(observation, scope_key)
    Agent-->>App: AgentResult(output, cost)

    Note over Agent: BaseAgent.execute() finishes:<br/>cost_record → audit_complete
```

---

## Pattern B: Full Pipeline (Intent → Strategy → Agent)

```mermaid
sequenceDiagram
    participant App
    participant IA as IIntentAnalyzer
    participant SS as StrategySelector
    participant ST as ICognitiveStrategy
    participant AP as AgentPool
    participant AG as LLMAgent
    participant IV as IVerifier

    App->>IA: analyze(query, context)
    IA-->>App: StructuredIntent(complexity=HIGH, requires_tools=true)

    App->>SS: select(intent, context)
    SS-->>App: ReActStrategy (complexity >= MEDIUM)

    App->>ST: execute(intent, context, pool, verifier)

    loop max_steps=6
        ST->>AP: dispatch(think_task)
        AP->>AG: execute(task, context)
        AG-->>AP: AgentResult(output)
        AP-->>ST: output

        alt output starts with "DONE:"
            ST-->>App: CognitiveResult
        end
    end

    ST->>IV: verify(output, context)
    IV-->>ST: VerificationResult(passed=true, score=0.92)

    ST-->>App: CognitiveResult(output, verification)
```

---

## Pattern C: Parallel Fan-out

```mermaid
sequenceDiagram
    participant Orch as Orchestrator
    participant AP as AgentPool
    participant A1 as Agent 1
    participant A2 as Agent 2
    participant A3 as Agent 3

    Orch->>AP: fan_out([task1, task2, task3], context)
    par concurrent
        AP->>A1: execute(task1, context)
    and
        AP->>A2: execute(task2, context)
    and
        AP->>A3: execute(task3, context)
    end
    A1-->>AP: AgentResult
    A2-->>AP: AgentResult
    A3-->>AP: AgentResult
    AP-->>Orch: list[AgentResult]
```

Used by `ParallelStrategy` and `code_analysis` example (one agent per class).

---

## BaseAgent.execute() — Cross-cutting Pipeline

```mermaid
flowchart LR
    IN([Task + Context]) --> RL[rate_limiter.acquire]
    RL --> BC[cost_tracker.enforce]
    BC --> AS[audit_logger.log_start]
    AS --> EX[_execute - domain logic]
    EX --> CR[cost_tracker.record]
    CR --> AC[audit_logger.log_complete]
    AC --> OUT([AgentResult])

    EX -- RetryableError / DegradedError --> AE[audit_logger.log_error]
    EX -- Exception --> FE[wrap FatalError]
    AE --> RERAISE([re-raise])
    FE --> RERAISE
```

`_execute()` is the only method subclasses implement. The pipeline is sealed.
