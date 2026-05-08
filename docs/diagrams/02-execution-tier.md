# Execution Tier — Class Diagram

`uaaf/execution/` — agent base classes, LLM loop, tool registry, agent pool.

```mermaid
classDiagram
    class BaseAgent {
        <<abstract dataclass>>
        +agent_id: str
        +cost_tracker: CostTracker
        +tracer: Tracer
        +audit_logger: AuditLogger
        +rate_limiter: RateLimiter
        +execute(task, context) AgentResult
        #_execute(task, context)* AgentResult
    }

    class LLMAgent {
        <<abstract dataclass>>
        +llm: ILLMProvider
        +tool_registry: ToolRegistry | None
        +model_policy: ModelPolicy
        +callbacks: ReActCallbacks
        +audit_token_usage: bool
        +select_model(query) ModelTier
        +budget_summary(usage, model) BudgetSummary
        +react_loop(request, max_rounds, domain, callbacks) tuple
        #_execute(task, context)* AgentResult
    }

    class ModelPolicy {
        <<dataclass>>
        +keywords: set[str]
        +word_count_threshold: int = 25
        +cheap_threshold: int = 5
    }

    class BudgetSummary {
        <<dataclass>>
        +input_tokens: int
        +output_tokens: int
        +total_tokens: int
        +window_size: int
        +pct_used: float
    }

    class ReActCallbacks {
        <<Protocol>>
        +on_thought(text)
        +on_action(tool_name, args)
        +on_observation(tool_name, result)
        +on_final(text)
    }

    class SilentCallbacks {
        +on_thought(text)
        +on_action(tool_name, args)
        +on_observation(tool_name, result)
        +on_final(text)
    }

    class PrintCallbacks {
        +on_thought(text)  💭
        +on_action(tool_name, args)  🔧
        +on_observation(tool_name, result)  📋
        +on_final(text)  ✅
    }

    class ToolRegistry {
        -_tools: dict[str, ITool]
        -_domains: dict[str, set[str]]
        +register(name, tool, allowed_domains)
        +run(tool_call, domain) str
        +run_all(tool_calls, domain) list
        +schemas() list[dict]
    }

    class ITool {
        <<Protocol>>
        +tool_id: str
        +schema: dict | None
        +execute(args)* Any
    }

    class AgentPool {
        <<dataclass>>
        +agents: list[BaseAgent]
        +fan_out(tasks, context) list[AgentResult]
        +fan_in(tasks, context) AgentResult
    }

    class Task {
        <<dataclass>>
        +task_id: str
        +payload: dict
        +estimated_cost: Cost | None
        +metadata: dict
    }

    class AgentResult {
        <<dataclass>>
        +task_id: str
        +output: Any
        +cost: Cost
        +success: bool
        +metadata: dict
    }

    BaseAgent <|-- LLMAgent : extends
    LLMAgent --> ModelPolicy : uses
    LLMAgent --> BudgetSummary : produces
    LLMAgent --> ReActCallbacks : fires
    LLMAgent --> ToolRegistry : delegates tool calls
    SilentCallbacks ..|> ReActCallbacks : implements
    PrintCallbacks ..|> ReActCallbacks : implements
    ToolRegistry --> ITool : manages
    AgentPool --> BaseAgent : orchestrates
    BaseAgent --> Task : receives
    BaseAgent --> AgentResult : returns
```

---

## react_loop() — 4 Cases

```mermaid
flowchart TD
    START([react_loop called]) --> ROUND[LLM complete]
    ROUND --> CHECK{tool_calls?}
    CHECK -- "[] empty" --> FINAL([return content])
    CHECK -- no --> FINAL
    CHECK -- yes --> EXEC[run tools via ToolRegistry]
    EXEC --> APPEND[append assistant+tool messages]
    APPEND --> LIMIT{max_rounds\nexceeded?}
    LIMIT -- no --> ROUND
    LIMIT -- yes --> SYNTH[synthesis request\ntools=None]
    SYNTH --> FINAL
```

| Case | Trigger | Result |
|---|---|---|
| 1 | Round 1, no `tool_calls` | return immediately |
| 2 | `tool_calls` present | execute, accumulate, continue |
| 3 | `tool_calls=[]` mid-round | LLM changed mind → return |
| 4 | `max_rounds` exceeded | synthesis request → return |

---

## ToolRegistry — Domain Allowlist

```python
reg = ToolRegistry()
reg.register("buy_stock", buy_tool, allowed_domains={"finance"})
reg.register("list_tasks", list_tool)   # no restriction

# domain="finance" → buy_stock allowed
await reg.run(tool_call, domain="finance")

# domain="chat" → PermissionError for buy_stock
await reg.run(tool_call, domain="chat")
```

`ITool` can be a bare `async def` (auto-wrapped) or a class implementing the Protocol.
