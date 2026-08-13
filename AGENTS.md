# uaaf-framework — Codex Instructions

## Golden Rule

**Check the framework before writing any new class or function.**
If the abstraction you need already exists in any package below → import it.
If it does not exist but feels generic (reusable beyond this feature) → **stop, ask the user, propose adding it to the framework** before writing it inline.

---

## Full Package Map

### Core

| Package | Import | Key exports |
|---|---|---|
| `ryuu-core` | `ryuu_core` | `ExecutionContext`, `ContextScope`, `Task`, `AgentResult`, `Cost`, `CostEstimate`, `ModelTier`, `StrategyId`, `FrameworkError`, `BudgetExceededError`, `RetryableError`, `RetryDecision`, `classify_external_error`, `retry_policy`, `IAuditLogger`, `ICostTracker`, `IRateLimiter`, `ITracer`, `NullAuditLogger`, `NullCostTracker`, `NullRateLimiter`, `NullTracer` |
| `ryuu-runtime` | `ryuu_runtime` | `RequestHandler`, `StrategySelector`, `IIntentAnalyzer`, `LLMIntentAnalyzer` |
| `ryuu-workflow` | `ryuu_workflow` | `WorkflowEngine`, `IWorkflowEngine`, `WorkflowResult`, `WorkflowStatus`, `StateMachine`, `IState`, `StateTransition`, `Workflow`, `Checkpoint`, `ICheckpointStore`, `FileCheckpointStore`, `InMemoryCheckpointStore` |

### Cognitive

| Package | Import | Key exports |
|---|---|---|
| `ryuu-cognitive` | `ryuu_cognitive` | `LLMCompactor`, `IConversationCompactor`, `HierarchicalCompactor`, `LLMQueryDecomposer`, `IQueryDecomposer`, `LLMQueryExpander`, `IQueryExpander`, `SynonymExpander`, `SubQuery`, `IAgentPool`, `ICognitiveStrategy`, `IVerifier`, `VerificationResult` |
| `ryuu-intent` | `ryuu_intent` | `LLMIntentAnalyzer`, `INTENT_SYSTEM_PROMPT`, `Difficulty`, `normalize_difficulty` |
| `ryuu-reasoning` | `ryuu_reasoning` | `Rule`, `RuleVerifier`, `Z3Verifier` |

### Execution

| Package | Import | Key exports |
|---|---|---|
| `ryuu-execution` | `ryuu_execution` | `BaseAgent`, `LLMAgent`, `AgentPool`, `Task`, `AgentResult`, `ITool`, `ToolRegistry`, `PrintCallbacks`, `ReActCallbacks`, `SilentCallbacks` |
| `ryuu-hooks` | `ryuu_hooks` | `HookRegistry`, `HookEvent`, `HookContext`, `PreExecuteContext`, `PostExecuteContext`, `PreLLMContext`, `PostLLMContext`, `PreToolContext`, `PostToolContext`, `OnErrorContext`, `OnBudgetExceededContext`, `OnRateLimitedContext`, `OnCompleteContext`, `WrapLLMHandler`, `WrapToolHandler` |
| `ryuu-guardrail` | `ryuu_guardrail` | `GuardrailPipeline`, `IGuardrail`, `GuardrailResult`, `GuardrailAction`, `GuardrailBlockedError`, `TrustLevel` |

### LLM Providers

| Package | Import | Key exports |
|---|---|---|
| `ryuu-providers-core` | `ryuu_providers_core` | `ILLMProvider`, `CompletionRequest`, `Message`, `Response`, `StreamChunk`, `TokenUsage`, `calculate_usd`, `PRICING`, `CONTEXT_WINDOW`, `CircuitBreaker`, `ProviderFallbackChain`, `ModelRouter` |
| `ryuu-providers` | `ryuu_providers` | Re-exports everything from `ryuu_providers_core` |
| `ryuu-providers-anthropic` | `ryuu_providers_anthropic` | `AnthropicProvider` |
| `ryuu-providers-openai` | `ryuu_providers_openai` | `OpenAIProvider` |

### Storage

| Package | Import | Key exports |
|---|---|---|
| `ryuu-storage-core` | `ryuu_storage_core` | `IKVStore`, `IBlobStore`, `ICollectionStore`, `IProfileStore`, `Item`, `ProfileEntry`, `StorageError`, `StorageNotFoundError`, `StorageConnectionError` |
| `ryuu-storage-memory` | `ryuu_storage_memory` | `InMemoryKVStore`, `InMemoryCollectionStore` |
| `ryuu-storage-sqlite` | `ryuu_storage_sqlite` | `SqliteKVStore`, `SqliteCollectionStore` |
| `ryuu-storage-jsonl` | `ryuu_storage_jsonl` | `JsonlCollectionStore` |
| `ryuu-storage-postgres` | `ryuu_storage_postgres` | `PostgresKVStore`, `PostgresCollectionStore`, `PostgresSessionStore`, `PostgresHandlerStateStore`, `PostgresProfileStore` |

### Knowledge

| Package | Import | Key exports |
|---|---|---|
| `ryuu-knowledge-base` | `ryuu_knowledge_base` | `IKnowledgeBackbone`, `ContextAssembler`, `QueryResult`, `AssembledContext`, `BackboneType` |
| `ryuu-knowledge-rag` | `ryuu_knowledge_rag` | `RAGBackbone`, `RAGPipeline`, `DenseRetriever`, `IRetriever`, `IVectorStore`, `InMemoryVectorStore`, `IChunker`, `RecursiveChunker`, `Chunk`, `SearchResult` |
| `ryuu-knowledge-memory` | `ryuu_knowledge_memory` | `MemoryBackbone`, `MemoryToolset`, `IMemoryStore`, `EpisodicMemoryStore`, `WorkingMemoryStore`, `MemoryEntry`, `MemoryLayer` |
| `ryuu-knowledge-graph` | `ryuu_knowledge_graph` | `GraphBackbone`, `IGraphStore`, `InMemoryGraphStore`, `NeighborGraphBackbone`, `Node`, `Edge` |

### Prompts & Skills

| Package | Import | Key exports |
|---|---|---|
| `ryuu-prompts` | `ryuu_prompts` | `PromptRegistry`, `PromptTemplate`, `PromptConfig`, `ToolDefinition`, `make_framework_registry`, `PromptSkill`, `PromptSkillRegistry`, `PromptSkillsToolset`, `parse_skill_file`, `list_prompt_skills_tool` |
| `ryuu-system-tools` | `ryuu_system_tools` | `SystemToolset` |

### Messaging

| Package | Import | Key exports |
|---|---|---|
| `ryuu-messaging-core` | `ryuu_messaging_core` | `ConversationManager`, `ChannelOrchestrator`, `ScopeDispatcher`, `MessageClassifier`, `Session`, `Turn`, `IncomingMessage`, `OutgoingMessage`, `IChannelAdapter`, `IChannelHandler`, `ISessionStore`, `InMemorySessionStore`, `KVSessionStore`, `IScopeResolver`, `DefaultScopeResolver`, `SingleTenantResolver`, `CancelToken` |
| `ryuu-messaging-cli` | `ryuu_messaging_cli` | `CLIAdapter` |
| `ryuu-messaging-telegram` | `ryuu_messaging_telegram` | `TelegramAdapter` |

### MCP

| Package | Import | Key exports |
|---|---|---|
| `ryuu-mcp-core` | `ryuu_mcp_core` | `IMCPClient`, `MCPServerConfig`, `MCPToolSpec` |
| `ryuu-mcp-client` | `ryuu_mcp_client` | `MCPClient`, `MCPTool`, `MCPToolset`, `MCPSkillsLoader`, `SkillRegistry`, `SkillManager`, `SkillManagerToolset` |

### Observability

| Package | Import | Key exports |
|---|---|---|
| `ryuu-observability-core` | `ryuu_observability_core` | `CostTracker`, `CostPolicy`, `ICostStore`, `UsageSnapshot`, `AuditLogger`, `AuditEvent`, `AuditConfig`, `verify_chain`, `RateLimiter`, `RatePolicy` |
| `ryuu-observability-otel` | `ryuu_observability_otel` | `Tracer`, `setup_tracing`, `get_current_correlation_id` |
| `ryuu-observability` | `ryuu_observability` | Re-exports both above |

### Eval

| Package | Import | Key exports |
|---|---|---|
| `ryuu-eval-core` | `ryuu_eval_core` | `EvalCase`, `EvalCaseTemplate`, `EvalRunner`, `CaseResult`, `ScoreResult`, `SuiteResult`, `ProgressEvent`, `ProgressEventType`, `Scorer` protocol, `EvalTarget` protocol |
| `ryuu-eval-scorers` | `ryuu_eval_scorers` | `ExactMatch`, `Contains`, `Regex`, `Constraint`, `Threshold`, `Composite`, `LLMJudge`, `SemanticSimilarity` |
| `ryuu-eval-oracle` | `ryuu_eval_oracle` | `IOracleStrategy`, `IInputSource`, `IProductionTarget`, `ReviewSchema`, `OracleFixture`, `OracleWorkflow`, `FileInputSource` |
| `ryuu-eval` | `ryuu_eval` | `build_eval_router`, HTTP/SSE layer, UI serving |

---

## Decision Tree (run this before writing code)

```
Need a new class/function?
        │
        ▼
Grep the package map above for the concept
        │
   Found it? ──YES──▶ Import it. Done.
        │
        NO
        │
        ▼
Is it generic / reusable beyond this one feature?
        │
   YES  │   NO
        │    └──▶ Write it locally in the module. Add a TODO comment
        │          noting it may belong in the framework later.
        ▼
STOP. Ask the user:
  "This looks like it belongs in ryuu-<package>.
   Shall I add it there before using it here?"

Wait for confirmation before implementing.
```

---

## Required Design Patterns

### Registry — for extensible dispatch (providers, backends, adapters)
```python
_REGISTRY: list[tuple[str, str, str, dict]] = [
    ("ENV_VAR", "module.path", "ClassName", {"kwarg": "value"}),
]

def _factory():
    for env_var, module_path, cls_name, kwargs in _REGISTRY:
        if os.environ.get(env_var):
            mod = __import__(module_path, fromlist=[cls_name])
            return getattr(mod, cls_name)(**kwargs)
    return None
```
Adding a new provider = one new line in the list. Zero changes elsewhere.

### Strategy — for swappable scorers, targets, backends
Construct strategies outside, inject them in. Never branch inside the runner/engine.

### Factory Method — for runner/agent/handler construction
Wiring belongs in the factory. The HTTP router / CLI / bot adapter never instantiates providers or scorers directly.

### Protocol / Interface — for cross-package contracts
Depend on the protocol (`IKVStore`, `Scorer`, `ILLMProvider`), not the concrete class. This keeps blast radius minimal when swapping implementations.

---

## Architectural Decisions (chốt — không override)

### Entry point duy nhất
`RequestHandler.handle()` là entry point cho mọi request production.
**Không gọi `agent.execute()` trực tiếp** trong product/app code — nó bypass cognitive tier, không có `strategy_id` trong context, không qua `StrategySelector`.

`ryuu.Agent` tạm thời giữ để không break examples, nhưng **không thêm feature mới vào đó**.
Mọi capability mới (thinking, best-of-N, classify) phải nằm ở cognitive tier.

### ReAct canonical
**`_react_loop()` trong `LLMAgent` (tool-calling JSON via provider API) là implementation duy nhất cho production.**
Đây là cách Codex / Cursor / Devin thực sự làm: gọi provider với `tools=[...]`,
loop trên `stop_reason == "tool_use"` cho đến khi `end_turn`. Provider đã RLHF để emit
tool_use blocks chuẩn — reliable hơn hẳn text-parse.

`ReActStrategy` (text-parse `DONE:/ACTION:`) chỉ là **academic demo** của paper ReAct 2022.
**Không dùng trong product code.** Nó tồn tại để minh hoạ paper, không phải để dispatch thật.

ReAct **không phải cognitive strategy** — nó là execution primitive khi LLM có tools.
Cognitive strategies thật là: Plan-then-Execute, Best-of-N, Reflection, Hierarchical,
Decomposition — tất cả đều wrap quanh `_react_loop()`, không thay thế nó.

### Classify độ khó
**`LLMIntentAnalyzer` là nguồn duy nhất cho classify.**
`_heuristic_difficulty` đã bị xóa. `AdaptiveStrategy` và `Agent(adaptive_compute=True)` đều
require `difficulty_fn` được truyền vào — không có default fallback.

### Thinking
Cognitive tier (`ThinkingStrategy`) quyết định *có* thinking không.
Provider adapter quyết định *cách* thinking (native / CoT fallback).
**Không inject `<thinking>` ở cả hai tầng cùng lúc** — double-inject.

---

## Strict Rules

- **No duplicate abstractions.** Any class that reimplements something in the package map above is wrong. Delete it and import.
- **No scorer classes in application code.** All scorers live in `ryuu_eval_scorers`. Application code only selects and configures them.
- **No if/elif provider chains.** Use the Registry pattern.
- **No hardcoded model strings scattered across files.** Model names belong in config or a registry entry.
- **Propose before adding.** If a generic abstraction is missing from the framework, ask the user before writing it ad-hoc. The framework is the source of truth.
- **Low blast radius.** Changes to one scorer/provider/storage backend must not affect others. Depend on interfaces, not concrete types.
- **Open/Closed.** Extend by adding (new registry entry, new class). Never modify existing logic to accommodate a new variant.


<claude-mem-context>
# Memory Context

# [uaaf-framework] recent context, 2026-06-02 11:44am GMT+9

Legend: 🎯session 🔴bugfix 🟣feature 🔄refactor ✅change 🔵discovery ⚖️decision
Format: ID TIME TYPE TITLE
Fetch details: get_observations([IDs]) | Search: mem-search skill

Stats: 18 obs (7,958t read) | 391,103t work | 98% savings

### Jun 2, 2026
7298 10:36a 🔵 OracleReviewPage Tab 4 — CrudReviewMatrix Architecture and DataView Capability Gap
7299 10:37a 🔵 Tab4_Review Full Implementation — Input Context and Popup Pattern Confirmed
7304 10:38a 🟣 OracleReviewPage — Input DataView + Popup/New-Tab Implementation Started
7306 10:40a 🟣 OracleReviewPage Tab 4 — Input Table/Call Chain + Popup + New-Tab Comparison Implemented
7307 10:42a 🟣 OracleReviewPage Tab 4 Input/Comparison Feature — Browser-Verified Working
7311 10:43a 🔄 OracleReviewPage — New-Tab Button Converted to Native Anchor, compareHref Hash-Router Fixed
7313 10:44a ✅ OracleReviewPage Tab 4 Feature — Production Build Complete, Verification Screenshot Timed Out
7315 " ✅ OracleReviewPage Tab 4 — New Tab Link href Confirmed Correct with Hash Router Format
7316 10:45a ✅ OracleReviewPage Full Diff Summary — All Changes in This Session Confirmed
7322 10:51a 🔵 OracleReviewPage Tab4 Input Data Structure — Fixture Context Schema Confirmed
7323 10:52a 🟣 reviewModel.ts — OmittedFieldVM and buildOmittedFieldRows Added for Input Table Display
7325 " 🟣 reviewModel — buildOmittedFieldRows Unit Test Added and Wired into OracleReviewPage
7327 " 🟣 ReviewComparePanel — "Not Expected" Omitted Fields Table Added to Oracle Review UI
7329 10:53a 🟣 OracleReviewPage Tab4 — "Not Expected" Omitted Fields Table Verified Working in Production
7333 10:54a 🟣 OracleReviewPage — ReviewComparePanel and ReviewCompareModal New Components Added
7337 10:57a 🔵 column_level_crud_matrix Fixture — Expected Shape Uses {cells: {entity: {field: cell}}} Wrapper
7338 " 🟣 ReviewComparePanel — Multi-Route Aggregate Warning Banner Added with Route Count Context
7340 10:58a 🟣 ReviewComparePanel Multi-Route Warning — Browser Verified Working on column_level_crud_matrix

Access 391k tokens of past work via get_observations([IDs]) or mem-search skill.
</claude-mem-context>